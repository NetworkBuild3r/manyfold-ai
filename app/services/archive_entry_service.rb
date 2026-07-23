# frozen_string_literal: true

# List and selectively extract entries from library archives (zip/7z/rar/…)
# without expanding the whole archive into the model folder.
class ArchiveEntryService
  include Archive::ListEntries
  include Archive::ExtractEntry
  include Archive::PreviewEntry

  MAX_LIST_ENTRIES = 100_000
  DEFAULT_PREVIEW_BATCH = 50
  DEFAULT_PREVIEW_STAGGER = 0.5

  class EntryTooLarge < StandardError; end
  class EntryNotFound < StandardError; end
  class UnsafePath < StandardError; end

  def initialize(model_file)
    @model_file = model_file
    @model = model_file.model
    @library = @model.library
  end
end
