# frozen_string_literal: true

module Archive
  # One associated image per SHA-512 on a model. Loose files win over an archive
  # member with the same bytes. Extra archive members are marked skipped (the
  # zip is left alone). Extra loose copies are removed so the next scan does
  # not attach them again.
  class CollapseDuplicateImages
    def self.call(model)
      new(model).call
    end

    def self.dedupe(model, images)
      images.group_by { |image| image.digest.presence }.flat_map do |digest, group|
        digest.nil? ? group : [keeper(model, group)]
      end
    end

    def self.keeper(model, images)
      images.min_by { |image| [rank(model, image), image.id.to_i] }
    end

    def self.rank(model, image)
      if image.is_a?(ModelFile)
        return 0 if image.id == model.preview_file_id
        return 1 if named?(image)

        2
      else
        return 3 if image.id == model.preview_archive_entry_id
        return 4 if named?(image)

        5
      end
    end

    def self.named?(image)
      name = image.is_a?(ArchiveEntry) ? image.basename.to_s : image.filename.to_s
      name.match?(PreviewFilePicker::NAMED_IMAGE)
    end

    def initialize(model)
      @model = model
    end

    def call
      fill_digests!
      collapse!
    end

    private

    def fill_digests!
      @model.model_files.find_each do |file|
        next unless file.is_image?
        next if file.digest.present?

        hashed = file.calculate_digest
        file.update_column(:digest, hashed) if hashed.present? # rubocop:disable Rails/SkipsModelValidations
      end

      pending = @model.archive_entries.images
        .where(digest: [nil, ""])
        .where.not(status: %w[skipped too_large])
        .includes(:model_file)
        .to_a
      pending.group_by(&:model_file_id).each_value { |entries| fill_archive_digests!(entries) }
    end

    def fill_archive_digests!(entries)
      file = entries.first.model_file
      return unless file&.is_archive? && file.exists_on_storage?

      Dir.mktmpdir("image-digest") do |dir|
        destinations = {}
        entries.each do |entry|
          next if entry.size.to_i > SiteSettings.max_file_extract_size

          destinations[entry.pathname] = File.join(dir, "#{entry.id}.bin")
        end
        next if destinations.empty?

        ArchiveEntryService.new(file).extract_entries_to!(destinations)
        entries.each do |entry|
          path = destinations[entry.pathname]
          next unless path && File.file?(path)

          hashed = Archive::AdoptImage.hexdigest(path)
          entry.update_column(:digest, hashed) if hashed.present? # rubocop:disable Rails/SkipsModelValidations
        end
      end
    rescue ArchiveEntryService::EntryTooLarge, ArchiveEntryService::EntryNotFound, ArchiveEntryService::UnsafePath
      nil
    end

    def collapse!
      sources.group_by(&:digest).each_value do |group|
        next if group.size < 2

        keep = self.class.keeper(@model, group)
        group.each do |image|
          next if image.id == keep.id && image.instance_of?(keep.class)

          drop!(image, keep)
        end
      end
    end

    def sources
      files = @model.model_files.reload.select { |file| file.is_image? && file.digest.present? }
      entries = @model.archive_entries.images.where.not(status: %w[skipped too_large preview_failed]).where.not(digest: [nil, ""]).to_a
      files + entries
    end

    def drop!(image, keep)
      reassign_preview!(image, keep)
      case image
      when ArchiveEntry
        image.update!(status: "skipped", error_message: "duplicate image")
      when ModelFile
        image.delete_from_disk_and_destroy
      end
    end

    def reassign_preview!(image, keep)
      case image
      when ModelFile
        return unless @model.preview_file_id == image.id
      when ArchiveEntry
        return unless @model.preview_archive_entry_id == image.id
      end

      case keep
      when ModelFile
        @model.update!(preview_file: keep)
      when ArchiveEntry
        @model.update!(preview_archive_entry: keep)
      end
    end
  end
end
