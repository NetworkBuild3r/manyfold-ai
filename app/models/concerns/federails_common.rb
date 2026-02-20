module FederailsCommon
  extend ActiveSupport::Concern
  include Federails::ActorEntity

  included do
    scope :local, -> { joins(:federails_actor).where("federails_actors.local": true) }
    scope :remote, -> { joins(:federails_actor).where("federails_actors.local": false) }
    # Includes local models and those without federails_actor (treated as local). Used for merge/bulk edit.
    scope :mergeable, -> { left_joins(:federails_actor).where("federails_actors.local IS NOT FALSE OR federails_actors.id IS NULL") }
  end

  # Listed in increasing order of priority
  FEDIVERSE_USERNAMES = {
    collection: :public_id,
    model: :public_id,
    creator: :slug,
    user: :username
  }

  def federails_actor
    return nil unless DatabaseDetector.table_ready? "federails_actors"
    return nil unless persisted?
    act = Federails::Actor.find_by(entity: self)
    if act.nil?
      act = create_federails_actor
      reload
    end
    act
  rescue NoMethodError, ActiveRecord::StatementInvalid
    # Just return nil if we get errors from not running on fully-migrated data
    nil
  end

  def local?
    federails_actor ? federails_actor.local? : true
  end

  def remote?
    !local?
  end
end
