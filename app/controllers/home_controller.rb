class HomeController < ApplicationController
  before_action :check_library_exists
  skip_after_action :verify_policy_scoped

  def index
    visible = policy_scope(Model)
    @recent_models = visible.includes(:preview_file, :creator, :collection, :tags).order(created_at: :desc).limit(8)
    @feed = local_timeline

    if current_user
      @pulse = current_user.library_pulse(visible)
      queue_ids = current_user.queued_model_ids.to_a
      @queue_models = if queue_ids.any?
        visible.where(id: queue_ids).includes(:preview_file, :creator, :collection, :tags).order(updated_at: :desc).limit(8)
      else
        Model.none
      end

      printed_ids = current_user.printed_model_ids.to_a
      unprinted = printed_ids.any? ? visible.where.not(id: printed_ids) : visible
      base = unprinted.includes(:preview_file, :creator, :collection, :tags)
      # Always shuffle; prefer models with photo previews so the strip isn't blank cards.
      @print_next = base.with_image_preview.in_random_order.limit(8).load
      @print_next = base.in_random_order.limit(8) if @print_next.empty?
    end
  end

  # Random never-printed model — decision helper for "what should I print?"
  def surprise
    skip_authorization
    unless current_user
      redirect_to new_user_session_path, alert: t("devise.failure.unauthenticated")
      return
    end

    visible = policy_scope(Model)
    printed_ids = current_user.printed_model_ids.to_a
    scope = printed_ids.any? ? visible.where.not(id: printed_ids) : visible
    model = scope.with_image_preview.in_random_order.first || scope.in_random_order.first
    if model
      redirect_to model, notice: t(".picked")
    else
      redirect_to models_path, notice: t(".empty")
    end
  end

  def welcome
    skip_authorization
  end

  def about
    skip_authorization
  end

  private

  def check_library_exists
    redirect_to new_library_path if Library.all.empty? # rubocop:disable Pundit/UsePolicyScope
  end

  def local_timeline
    [Model, Creator, Collection].map do |model|
      query = policy_scope(model)
      query = query.includes(:federails_actor) if SiteSettings.federation_enabled?
      query.order(updated_at: :desc).limit(20)
    end.flatten.sort_by(&:updated_at).last(20).reverse
  end
end
