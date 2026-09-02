class ModelFileUploader < ApplicationUploader
  class Attacher
    def store_key
      @record.model.library.storage_key
    end
  end

  def generate_location(io, record: nil, derivative: nil, metadata: {}, **)
    return super unless record&.valid?

    location = record.path_within_library(derivative: derivative)
    LibraryPathJail.assert_within!(record.model.library.path, location)
    location
  end
end
