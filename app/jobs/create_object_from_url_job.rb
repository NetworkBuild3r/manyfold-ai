class CreateObjectFromUrlJob < ApplicationJob
  queue_as :low
  unique :until_executed

  def perform(url:, collection_id: nil, owner: nil, owner_id: nil)
    return if Link.find_by(url: url)

    owner ||= User.find(owner_id) if owner_id.present?
    deserializer = Link.deserializer_for(url: url)
    common_options = {
      name: "Importing from #{url.split("://").last} ...",
      links_attributes: [{url: url}]
    }
    object = case deserializer&.capabilities&.dig(:class)&.name
    when "Model"
      Model.new(common_options.merge({
        library: Library.default,
        path: SecureRandom.uuid,
        collection_id: collection_id
      }))
    when "Creator"
      Creator.new(common_options)
    when "Collection"
      Collection.new(common_options)
    end
    return unless object

    object.owner = owner if owner && object.respond_to?(:owner=)
    object.save
    if object.persisted?
      Permissions::ApplyPreset.call(object, owner: owner)
      object.links.first.update_metadata_from_link_later(organize: true)
    end
  end
end
