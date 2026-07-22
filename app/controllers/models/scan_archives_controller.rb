# frozen_string_literal: true

class Models::ScanArchivesController < ApplicationController
  before_action :get_model

  def create
    authorize @model, :scan?
    @model.scan_archives_later
    redirect_back_or_to @model, notice: t(".started")
  end

  private

  def get_model
    @model = policy_scope(Model).find_param(params[:model_id])
  end
end
