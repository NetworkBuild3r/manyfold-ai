# frozen_string_literal: true

module Archive
  # Copy an image found inside an archive onto the model when no existing image
  # has the same SHA-512 digest. ModelFile#calculate_digest is SHA-512, so this
  # matches files the scanner already hashed. If the model has no on-disk image
  # preview, the adopted or matching file becomes preview_file (image search).
  class AdoptImage
    def self.call(...)
      new(...).call
    end

    def initialize(model:, source_path:, filename:)
      @model = model
      @source_path = source_path
      @filename = filename
    end

    def call
      return unless File.file?(@source_path)

      digest = sha512(@source_path)
      return if digest.blank?

      file = matching_image(digest) || create_image!(digest)
      assign_preview!(file)
      file
    end

    private

    def matching_image(digest)
      known = @model.model_files.where(digest: digest).detect(&:is_image?)
      return known if known

      @model.model_files.where(digest: [nil, ""]).find do |file|
        next unless file.is_image?

        hashed = file.calculate_digest
        next if hashed.blank?

        file.update_column(:digest, hashed) if file.digest != hashed
        hashed == digest
      end
    end

    def create_image!(digest)
      filename = unique_filename
      dest = File.join(@model.library.path, @model.path, filename)
      FileUtils.mkdir_p(File.dirname(dest))
      FileUtils.cp(@source_path, dest)
      @model.model_files.create!(filename: filename, digest: digest)
    end

    def unique_filename
      base = File.basename(@filename.to_s)
      base = "image.png" if base.blank? || base == "." || base == ".."
      ext = File.extname(base)
      stem = File.basename(base, ext)
      candidate = base
      n = 1
      while name_taken?(candidate)
        candidate = "#{stem}-#{n}#{ext}"
        n += 1
      end
      candidate
    end

    def name_taken?(filename)
      @model.model_files.exists?(filename: filename) ||
        File.exist?(File.join(@model.library.path, @model.path, filename))
    end

    def assign_preview!(file)
      return unless file&.is_image?

      current = @model.preview_file
      return if current&.is_image? && current.exists_on_storage?

      @model.update!(preview_file: file) unless @model.preview_file_id == file.id
    end

    def sha512(path)
      digest = Digest::SHA512.new
      File.open(path, "rb") do |io|
        while (chunk = io.read(1.megabyte))
          digest.update(chunk)
        end
      end
      digest.hexdigest
    end
  end
end
