# frozen_string_literal: true

module Archive
  # Delete confirmation for a loose file that names any archive it will also
  # be removed from, or stay inside if that archive cannot be rewritten
  # (INIT-001/SPEC-005). cache memoizes writability per archive id.
  class DeleteConfirmation
    def self.call(file, base:, cache: {})
      archives = file.adopted_source_archives.to_a
      return base if archives.empty?

      writable, kept = archives.partition do |archive|
        cache.fetch(archive.id) { cache[archive.id] = Archive::RemoveEntries.writable?(archive) }
      end
      message = [base]
      if writable.any?
        message << I18n.t("model_files.destroy.confirm_archive_remove", file: file.filename, archives: writable.map(&:filename).to_sentence)
      end
      if kept.any?
        message << I18n.t("model_files.destroy.confirm_archive_keep", file: file.filename, archives: kept.map(&:filename).to_sentence)
      end
      message.join(" ")
    end
  end
end
