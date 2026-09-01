# frozen_string_literal: true

# INIT-017/SPEC-002 — Creators/collections a user may assign on model edit.
# View-permission local scope (not UpdateScope), always including the model's current association.
module Model
  class AssignableAssociations
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
      scope = Pundit.policy_scope!(@user, klass)
      scope = scope.local if scope.respond_to?(:local)
      scope.order(Arel.sql("LOWER(#{klass.table_name}.name) ASC"))
    end

    def merge_current(relation, current)
      return relation if current.blank?
      return relation if relation.where(id: current.id).exists?

      # Include current even if outside view scope so the control never blanks an existing assign.
      ids = relation.pluck(:id) + [current.id]
      relation.klass.where(id: ids).order(Arel.sql("LOWER(#{relation.klass.table_name}.name) ASC"))
    end
  end
end
