# frozen_string_literal: true

# Application-layer publish helper. Does NOT auto-publish creators —
# the creator (and license) must already satisfy validate_publishable.
class Model::Publish
  class NotPublishable < StandardError; end

  def self.call(model, permission: "view")
    new(model).call(permission: permission)
  end

  def initialize(model)
    @model = model
  end

  def call(permission: "view")
    @model.assign_attributes(
      caber_relations_attributes: [{subject: nil, permission: permission}]
    )
    unless @model.valid?
      raise NotPublishable, @model.errors.full_messages.join(", ")
    end

    @model.save!
    @model
  end
end
