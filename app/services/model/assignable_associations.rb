# frozen_string_literal: true

# INIT-017/SPEC-002 — Creators/collections a user may assign on model edit.
# View-permission + mergeable (treated-as-local) scope — not .local INNER JOIN,
# which empties when federation is off and federails_actor rows were never created.
# Always includes the model's current association.
class Model::AssignableAssociations
  def initialize(user:, model: nil)
    @user = user
    @model = model
  end

  def creators
    merge_current(base_scope(Creator), @model&.creator)
  end

  def collections
    merge_current(base_scope(Collection), @model&.collection)
  end

  def assignable_creator_id?(id)
    return true if id.blank?

    creators.where(id: id).exists?
  end

  def assignable_collection_id?(id)
    return true if id.blank?

    collections.where(id: id).exists?
  end

  private

  def base_scope(klass)
    # Use mergeable, not .local: when federation is off, creators have no federails_actor
    # rows, so .local (INNER JOIN) returns empty while local? still treats them as local.
    scope = Pundit.policy_scope!(@user, klass)
    scope = scope.mergeable if scope.respond_to?(:mergeable)
    scope.order(Arel.sql("LOWER(#{klass.table_name}.name) ASC"))
  end

  def merge_current(relation, current)
    return relation if current.blank?
    return relation if relation.where(id: current.id).exists?

    ids = relation.pluck(:id) + [current.id]
    relation.klass.where(id: ids).order(Arel.sql("LOWER(#{relation.klass.table_name}.name) ASC"))
  end
end
