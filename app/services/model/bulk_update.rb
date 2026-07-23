# frozen_string_literal: true

class Model::BulkUpdate
  def self.call(models:, attributes:, add_tags: [], remove_tags: [])
    new(models: models, attributes: attributes, add_tags: add_tags, remove_tags: remove_tags).call
  end

  def initialize(models:, attributes:, add_tags: [], remove_tags: [])
    @models = models
    @attributes = attributes
    @add_tags = Set.new(add_tags)
    @remove_tags = Set.new(remove_tags)
  end

  def call
    @models.find_each do |model|
      next unless Model::Update.call(model, @attributes)

      existing_tags = Set.new(model.tag_list)
      model.tag_list = existing_tags + @add_tags - @remove_tags
      model.save
    end
  end
end
