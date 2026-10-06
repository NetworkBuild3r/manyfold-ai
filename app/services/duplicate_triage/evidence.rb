# frozen_string_literal: true

require "digest"
require "set"

module DuplicateTriage
  # Plain value object: every number the judge sees (INIT-031/SPEC-003, D-5, D-8).
  class Evidence
    SHARED_FILENAME_CAP = 40
    UNIQUE_FILENAME_CAP = 25
    PROMPT_KEYS = %i[
      name_a
      name_b
      path_a
      path_b
      file_count_a
      file_count_b
      shared_filenames
      unique_filenames_a
      unique_filenames_b
      shared_bytes
      unique_bytes_a
      unique_bytes_b
      total_bytes_a
      total_bytes_b
      containment
      byte_containment
      jaccard
      nested
      creator_a
      creator_b
      lossless
      contained_side
      container_side
      contained_files_all_images
      fingerprint
    ].freeze
    IMAGE_EXTENSIONS = %w[.jpg .jpeg .png .webp .gif].freeze

    def self.build(model_a, model_b, files: nil)
      low, high = [model_a, model_b].minmax_by(&:id)
      index = files || FileIndex.load([low.id, high.id])
      new(
        model_a: low,
        model_b: high,
        rows_a: index.rows_for(low.id),
        rows_b: index.rows_for(high.id),
        total_bytes_a: index.total_bytes_for(low.id),
        total_bytes_b: index.total_bytes_for(high.id)
      )
    end

    def initialize(model_a:, model_b:, rows_a:, rows_b:, total_bytes_a:, total_bytes_b:)
      @model_a = model_a
      @model_b = model_b
      @rows_a = rows_a
      @rows_b = rows_b
      @total_bytes_a = total_bytes_a.to_i
      @total_bytes_b = total_bytes_b.to_i
    end

    attr_reader :total_bytes_a, :total_bytes_b

    def to_prompt_h
      PROMPT_KEYS.to_h { |key| [key, public_send(key)] }
    end

    def name_a = @model_a.name
    def name_b = @model_b.name
    def path_a = @model_a.path
    def path_b = @model_b.path
    def creator_a = @model_a.creator&.name
    def creator_b = @model_b.creator&.name
    def file_count_a = digests_a.size
    def file_count_b = digests_b.size

    def shared_filenames
      filenames_for(shared_digest_set, @rows_a + @rows_b).first(SHARED_FILENAME_CAP)
    end

    def unique_filenames_a
      filenames_for(unique_digest_set(@rows_a), @rows_a).first(UNIQUE_FILENAME_CAP)
    end

    def unique_filenames_b
      filenames_for(unique_digest_set(@rows_b), @rows_b).first(UNIQUE_FILENAME_CAP)
    end

    def shared_bytes
      shared_digests.sum { |digest| size_for(digest, @rows_a) }
    end

    def unique_bytes_a
      unique_digest_set(@rows_a).sum { |digest| size_for(digest, @rows_a) }
    end

    def unique_bytes_b
      unique_digest_set(@rows_b).sum { |digest| size_for(digest, @rows_b) }
    end

    def byte_containment
      smaller = [total_bytes_a, total_bytes_b].min
      return 0.0 if smaller.zero?

      shared_bytes.to_f / smaller
    end

    def containment
      smaller = [file_count_a, file_count_b].min
      return 0.0 if smaller.zero?

      shared_digests.size.to_f / smaller
    end

    def jaccard
      union = (digest_set(@rows_a) | digest_set(@rows_b)).size
      return 0.0 if union.zero?

      shared_digests.size.to_f / union
    end

    def nested
      Ancestry.nested?(@model_a, @model_b)
    end
    alias_method :nested?, :nested

    # Side with fewer bytes (tie → a). Every one of its files exists byte-identical
    # in the other side when `lossless` is true: merging loses no file.
    def contained_side
      (total_bytes_a <= total_bytes_b) ? "a" : "b"
    end

    def container_side
      (contained_side == "a") ? "b" : "a"
    end

    def lossless
      smaller_total = (contained_side == "a") ? total_bytes_a : total_bytes_b
      return false if smaller_total.zero?

      rows = (contained_side == "a") ? @rows_a : @rows_b
      digest_set(rows).any? && unique_digest_set(rows).empty?
    end
    alias_method :lossless?, :lossless

    # True when the contained side holds nothing but images (a promo-image stub next to the real pack).
    def contained_files_all_images
      rows = (contained_side == "a") ? @rows_a : @rows_b
      rows.any? && rows.all? { |row| IMAGE_EXTENSIONS.include?(File.extname(row.filename).downcase) }
    end

    def fingerprint
      Digest::SHA256.hexdigest(fingerprint_payload)
    end

    def shared_digests = shared_digest_set.sort
    def digests_a = digest_set(@rows_a).sort
    def digests_b = digest_set(@rows_b).sort

    private

    def fingerprint_payload
      [shared_digests.join("|"), digests_a.join("|"), digests_b.join("|")].join("#")
    end

    def shared_digest_set
      digest_set(@rows_a) & digest_set(@rows_b)
    end

    def unique_digest_set(rows)
      digest_set(rows) - shared_digest_set
    end

    def digest_set(rows)
      Set.new(rows.map(&:digest))
    end

    def filenames_for(digests, rows)
      rows.select { |row| digests.include?(row.digest) }.map(&:filename).uniq.sort
    end

    def size_for(digest, rows)
      match = rows.select { |row| row.digest == digest }.min_by(&:filename)
      match&.size.to_i
    end
  end
end
