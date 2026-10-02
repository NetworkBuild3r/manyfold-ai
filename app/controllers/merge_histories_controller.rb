# frozen_string_literal: true

# Library-wide log of model merges, so a merge is reviewable (and undoable) from one place
# instead of leaving its trace scattered across the Problems list.
class MergeHistoriesController < ApplicationController
  def index
    authorize MergeHistory
    @merge_histories = policy_scope(MergeHistory)
      .includes(:target_model)
      .order(created_at: :desc, id: :desc)
      .page(params[:page] || 1)
      .per(50)
  end
end
