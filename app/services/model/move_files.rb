# frozen_string_literal: true

# Move storage objects after a model path/library change.
# Callers must capture from_library/from_path *before* save clears dirty state,
# or use Model::Update which does that.
class Model::MoveFiles
  def self.call(model, from_library:, from_path:)
    new(model).call(from_library: from_library, from_path: from_path)
  end

  def initialize(model)
    @model = model
  end

  def call(from_library:, from_path:)
    @model.model_files.each(&:reattach!)
    from_library.storage.delete_prefixed(from_path) if from_library && from_path.present?
    @model
  end
end
