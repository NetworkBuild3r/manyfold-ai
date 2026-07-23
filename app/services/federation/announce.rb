# frozen_string_literal: true

# Application-layer federation announcements. Models/concerns call these
# instead of embedding Federails/Activity job orchestration inline.
module Federation
  class Announce
    class << self
      def model_created(model)
        return if suppress?(model)
        return unless SiteSettings.federation_enabled?
        return unless model.public?

        Activity::ModelPublishedJob.set(wait: 5.seconds).perform_later(model.id)
      end

      def model_updated(model)
        return if suppress?(model)
        return unless SiteSettings.federation_enabled?

        if model.creator_previously_changed? && model.creator&.public?
          Activity::ModelPublishedJob.set(wait: 5.seconds).perform_later(model.id)
        elsif model.collection_previously_changed? && model.collection&.public?
          Activity::ModelCollectedJob.set(wait: 5.seconds).perform_later(model.id, model.collection.id)
        elsif model.just_became_public?
          Activity::ModelPublishedJob.set(wait: 5.seconds).perform_later(model.id)
        elsif model.public? && model.send(:noteworthy_change?)
          Activity::ModelUpdatedJob.set(wait: 5.seconds).perform_later(model.id)
        end
      end

      def collection_created(collection)
        return if suppress?(collection)
        return unless SiteSettings.federation_enabled?
        return unless collection.public?

        Activity::CollectionPublishedJob.set(wait: 5.seconds).perform_later(collection.id)
      end

      def collection_updated(collection)
        return if suppress?(collection)
        return unless SiteSettings.federation_enabled?
        return unless collection.just_became_public?

        Activity::CollectionPublishedJob.set(wait: 5.seconds).perform_later(collection.id)
      end

      def followable_create(record)
        return if Current.scan_batch_id.present?
        return if suppress?(record)
        return unless SiteSettings.federation_enabled?

        followable_activity(record, "Create")
      end

      def followable_update(record)
        return if Current.scan_batch_id.present?
        return if suppress?(record)
        return unless SiteSettings.federation_enabled?
        return if recently_posted?(record)

        followable_activity(record, "Update")
      end

      def followable_activity(record, action)
        return unless record.respond_to?(:owning_actor) && record.owning_actor
        return unless record.federails_actor

        Federails::Activity.create!(
          actor: record.owning_actor,
          action: action,
          entity: record.federails_actor,
          created_at: record.updated_at
        )
      end

      private

      def suppress?(record)
        return true if record.respond_to?(:suppress_federation_announce?) && record.suppress_federation_announce?
        return true if record.respond_to?(:suppress_announce) && record.suppress_announce

        false
      end

      def recently_posted?(record)
        timeout = Followable::TIMEOUT
        return false unless DatabaseDetector.table_ready?("federails_activities")
        return false unless record.federails_actor

        Federails::Activity.exists?(
          action: ["Create", "Update"],
          entity: record.federails_actor,
          created_at: timeout.minutes.ago..
        )
      end
    end
  end
end
