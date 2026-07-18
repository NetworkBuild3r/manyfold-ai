# frozen_string_literal: true

class Components::ModelCardPreview < Components::Base
  include Phlex::Rails::Helpers::LinkTo
  include Phlex::Rails::Helpers::ButtonTo

  register_output_helper :server_indicator
  register_value_helper :policy

  def initialize(model:, editable:, actor: nil, eager_preview: false, gallery: false)
    @model = model
    @editable = editable
    @actor = actor || model.federails_actor
    @eager_preview = eager_preview
    @gallery = gallery
  end

  def view_template
    div(class: "relative w-full aspect-[4/3]") do
      selection_bubble if @editable
      personal_list_actions if current_user
      if @actor && !@actor.local
        PreviewFrame(object: @model, lite: true, eager: @eager_preview)
      elsif @gallery && gallery_eligible?
        button type: "button",
          class: "block w-full h-full p-0 m-0 border-0 bg-transparent cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary-500",
          data: {
            action: "click->model-gallery#open",
            model_gallery_model_url_param: model_path(@model),
            model_gallery_gallery_url_param: gallery_model_path(@model),
            model_gallery_model_name_param: @model.name
          },
          aria: {haspopup: "dialog", label: translate("components.model_gallery.preview_label", name: @model.name)} do
          PreviewFrame(object: @model, lite: true, eager: @eager_preview)
        end
      else
        link_to @model, class: "block no-underline", data: {turbo_frame: "_top"}, aria: {label: translate("components.model_card.open_button.label", name: @model.name)} do
          PreviewFrame(object: @model, lite: true, eager: @eager_preview)
        end
      end
    end
  end

  private

  def gallery_eligible?
    file = @model.preview_file
    file.present? && file.is_image?
  end

  def selection_bubble
    button type: "button",
      class: "model-card-selection-bubble absolute top-2 left-2 z-20 w-5 h-5 rounded-full border-2 border-white dark:border-secondary-300 bg-white/40 dark:bg-secondary-500/70 flex items-center justify-center focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 transition-opacity",
      data: {model_id: @model.public_id, action: "click->model-list-selection#toggle", model_list_selection_target: "bubble"},
      aria: {label: t("models.list.selection.select"), pressed: "false"} do
      i(class: "bi bi-check-lg model-card-selection-check text-white text-xs opacity-0 transition-opacity pointer-events-none font-bold", "aria-hidden": "true")
    end
  end

  def personal_list_actions
    queued = current_user.queued_model_ids.include?(@model.id)
    favorited = current_user.favorited_model_ids.include?(@model.id)

    div(class: "absolute top-2 right-2 z-20 flex gap-1") do
      button_to toggle_queue_model_path(@model),
        method: :post,
        class: list_action_class(active: queued),
        form: {class: "inline", data: {turbo: false}},
        title: queued ? t("models.show.dequeue") : t("models.show.queue"),
        aria: {label: queued ? t("models.show.dequeue") : t("models.show.queue"), pressed: queued} do
        i(class: "bi bi-#{queued ? "bookmark-fill" : "bookmark"} text-sm", "aria-hidden": "true")
      end
      button_to toggle_favorite_model_path(@model),
        method: :post,
        class: list_action_class(active: favorited),
        form: {class: "inline", data: {turbo: false}},
        title: favorited ? t("models.show.unfavorite") : t("models.show.favorite"),
        aria: {label: favorited ? t("models.show.unfavorite") : t("models.show.favorite"), pressed: favorited} do
        i(class: "bi bi-#{favorited ? "heart-fill" : "heart"} text-sm", "aria-hidden": "true")
      end
    end
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
