# frozen_string_literal: true

class MergeHistoryPolicy < ApplicationPolicy
  def index?
    user&.is_moderator?
  end

  class Scope < ApplicationPolicy::Scope
    def resolve
      @user&.is_moderator? ? scope : scope.none
    end
  end
end
