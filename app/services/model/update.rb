# frozen_string_literal: true

# Assign attributes, persist, then move storage if path/library changed.
# Replaces the before_update :move_files operation callback.
class Model::Update
  def self.call(model, attributes)
    new(model).call(attributes)
  end

  def initialize(model)
    @model = model
  end

  def call(attributes)
    attrs = attributes.respond_to?(:to_unsafe_h) ? attributes.to_unsafe_h : attributes.to_h
    attrs = attrs.deep_stringify_keys

    organize = attrs.delete("organize")
    organize = (organize == true || organize.to_s == "true")
    preset = attrs.delete("permission_preset")

    @model.assign_attributes(attrs)
    @model.permission_preset = preset if preset.present? && @model.respond_to?(:permission_preset=)
    @model.path = @model.formatted_path if organize

    needs_move = @model.needs_storage_move?
    from_library = @model.storage_move_from_library
    from_path = @model.storage_move_from_path

    ok = @model.save
    if ok && needs_move
      Model::MoveFiles.call(@model, from_library: from_library, from_path: from_path)
    end
    # Apply Caber preset/owner after save (replaces after_commit callbacks when disabled).
    if ok && (preset.present? || @model.instance_variable_get(:@permission_preset).present? || @model.instance_variable_get(:@owner).present?)
      Permissions::ApplyPreset.call(@model, permission_preset: preset)
    end
    ok
  end
end
