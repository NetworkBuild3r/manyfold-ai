class ProblemPolicy < ApplicationPolicy
  def index?
    user&.is_moderator?
  end

  def show?
    user&.is_moderator?
  end

  def resolve?
    all_of(
      user&.is_moderator?,
      Pundit::PolicyFinder.new(record.problematic).policy.new(user, record.problematic).send(:"#{record.resolution_strategy}?")
    )
  end

  def merge?
    return false unless user&.is_moderator?
    return false unless record.category == "duplicate"

    pair = Problem::DuplicatePair.build(record)
    return false unless pair&.mergeable?

    pair.other_models.all? { |model| ModelPolicy.new(user, model).merge? } &&
      ModelPolicy.new(user, pair.model).merge?
  end

  class Scope < ApplicationPolicy::Scope
    def resolve
      @user.is_moderator? ? scope : scope.none
    end
  end
end
