# frozen_string_literal: true

# Heart / bookmark controls on model cards. Stable DOM id so turbo_stream
# can swap icons in place without a full page reload.
class Components::ModelListActions < Components::Base
  include Phlex::Rails::Helpers::ButtonTo

  def initialize(model:)
    @model = model
  end

  def view_template
    return unless current_user

    queued = current_user.queued_model_ids.include?(@model.id)
    favorited = current_user.favorited_model_ids.include?(@model.id)

    div(id: dom_id, class: "absolute top-2 right-2 z-20 flex gap-1") do
      button_to toggle_queue_model_path(@model),
        method: :post,
        class: list_action_class(active: queued),
        form: {class: "inline"},
        title: queued ? t("models.show.dequeue") : t("models.show.queue"),
        aria: {label: queued ? t("models.show.dequeue") : t("models.show.queue"), pressed: queued} do
        i(class: "bi bi-#{queued ? "bookmark-fill" : "bookmark"} text-sm", "aria-hidden": "true")
      end
      button_to toggle_favorite_model_path(@model),
        method: :post,
        class: list_action_class(active: favorited),
        form: {class: "inline"},
        title: favorited ? t("models.show.unfavorite") : t("models.show.favorite"),
        aria: {label: favorited ? t("models.show.unfavorite") : t("models.show.favorite"), pressed: favorited} do
        i(class: "bi bi-#{favorited ? "heart-fill" : "heart"} text-sm", "aria-hidden": "true")
      end
    end
  end

  def self.dom_id_for(model)
    "model_#{model.to_param}_list_actions"
  end

  private

  def dom_id
    self.class.dom_id_for(@model)
  end

  def list_action_class(active:)
    base = "inline-flex items-center justify-center w-9 h-9 min-w-[44px] min-h-[44px] sm:w-8 sm:h-8 sm:min-w-0 sm:min-h-0 rounded-full shadow-sm border backdrop-blur-sm focus-visible:ring-2 focus-visible:ring-primary-500"
    if active
      "#{base} bg-primary-600 text-white border-primary-700"
    else
      "#{base} bg-white/90 dark:bg-secondary-900/90 text-secondary-800 dark:text-secondary-100 border-secondary-200/80 dark:border-secondary-600 hover:border-primary-400"
    end
  end
end
