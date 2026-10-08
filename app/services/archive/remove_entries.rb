# frozen_string_literal: true

require "ffi-libarchive"

module Archive
  # Rewrite an archive without some of its entries (INIT-001/SPEC-004). The new
  # archive is written next to the original, re-read to verify it holds exactly
  # the expected entries, then renamed over the original. On any failure the
  # original is left byte-identical. Formats libarchive cannot write back (RAR,
  # unsupported filters) and non-filesystem libraries are reported unwritable.
  class RemoveEntries
    WRITABLE_FORMATS = [::Archive::FORMAT_ZIP, ::Archive::FORMAT_TAR, ::Archive::FORMAT_7ZIP].freeze
    WRITABLE_FILTERS = [
      ::Archive::COMPRESSION_NONE, ::Archive::COMPRESSION_GZIP,
      ::Archive::COMPRESSION_BZIP2, ::Archive::COMPRESSION_XZ
    ].freeze
    # zip and 7z compress per entry; an outer filter on them is not writable.
    CONTAINER_FORMATS = [::Archive::FORMAT_ZIP, ::Archive::FORMAT_7ZIP].freeze

    class Unwritable < StandardError; end
    class VerifyFailed < StandardError; end

    Result = Struct.new(:status, :removed, :message, keyword_init: true)

    def self.call(...)
      new(...).call
    end

    def self.writable?(model_file)
      new(model_file: model_file, pathnames: []).writable?
    end

    def initialize(model_file:, pathnames:)
      @model_file = model_file
      @model = model_file.model
      @library = @model.library
      @pathnames = pathnames.map { |p| normalize(p) }.to_set
    end

    def writable?
      !!safe_format
    end

    def call
      return Result.new(status: :noop, removed: []) if @pathnames.empty?

      format, filter = safe_format || raise(Unwritable, "archive format not writable")
      temp = temp_path
      kept, removed = rewrite!(temp, format, filter)
      return Result.new(status: :noop, removed: []) if removed.empty?

      verify!(temp, kept, removed)
      File.chmod(File.stat(archive_path).mode, temp)
      File.rename(temp, archive_path)
      Result.new(status: :removed, removed: removed)
    rescue Unwritable => e
      Result.new(status: :unwritable, removed: [], message: e.message)
    ensure
      FileUtils.rm_f(temp) if temp && File.exist?(temp)
    end

    private

    def archive_path
      LibraryPathJail.assert_within!(@library.path, @model_file.path_within_library)
      File.join(@library.path, @model_file.path_within_library)
    end

    def temp_path
      File.join(File.dirname(archive_path), ".#{File.basename(archive_path)}.#{SecureRandom.hex(6)}.rewrite")
    end

    def safe_format
      archive_format
    rescue ::Archive::Error, SystemCallError, LibraryPathJail::EscapeError
      nil
    end

    # [format, filter] when both can be written back, else nil.
    def archive_format
      return unless @library.storage_service == "filesystem"
      return unless File.file?(archive_path)

      format, filter = ::Archive::Reader.open_filename(archive_path) do |reader|
        reader.next_header
        [reader.format, reader.compression]
      end
      base = format & ::Archive::FORMAT_BASE_MASK
      return unless WRITABLE_FORMATS.include?(base) && WRITABLE_FILTERS.include?(filter)
      return if CONTAINER_FORMATS.include?(base) && filter != ::Archive::COMPRESSION_NONE

      [format, filter]
    end

    def rewrite!(temp, format, filter)
      kept = []
      removed = []
      ::Archive::Reader.open_filename(archive_path) do |reader|
        ::Archive::Writer.open_filename(temp, filter, format) do |writer|
          while (entry = reader.next_header)
            pathname = normalize(entry.pathname)
            if entry.file? && @pathnames.include?(pathname)
              removed << pathname
              next
            end

            writer.write_header(entry)
            reader.read_data { |chunk| writer.write_data(chunk) } if entry.file?
            kept << pathname
          end
        end
      end
      [kept, removed]
    end

    def verify!(temp, kept, removed)
      found = []
      ::Archive::Reader.open_filename(temp) do |reader|
        while (entry = reader.next_header)
          found << normalize(entry.pathname)
        end
      end
      return if found.sort == kept.sort && !found.intersect?(removed)

      raise VerifyFailed, "rewritten archive has #{found.size} entries, expected #{kept.size}"
    end

    def normalize(pathname)
      pathname.to_s.delete_prefix("./").tr("\\", "/")
    end
  end
end
