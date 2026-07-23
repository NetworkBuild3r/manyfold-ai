# frozen_string_literal: true

# Application-layer publish helper. Does NOT auto-publish creators —
# the creator (and license) must already satisfy validate_publishable.
# Uses Model::Update so path/library storage moves stay consistent.
class Model::Publish
  class NotPublishable < StandardError; end

  def self.call(model, permission: "view", **attributes)
    new(model).call(permission: permission, **attributes)
  end

  def initialize(model)
    @model = model
  end

  def call(permission: "view", **attributes)
    attrs = attributes.stringify_keys
    attrs["caber_relations_attributes"] = [{subject: nil, permission: permission}]
    unless Model::Update.call(@model, attrs)
      raise NotPublishable, @model.errors.full_messages.join(", ")
    end

    @model
  end
end
