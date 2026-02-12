# frozen_string_literal: true

class Components::ModelCard < Components::Base
  include Phlex::Rails::Helpers::ImageTag
  include Phlex::Rails::Helpers::Sanitize
  include Phlex::Rails::Helpers::LinkTo

  register_output_helper :server_indicator
  register_value_helper :policy

  def initialize(model:)
    @model = model
    @actor = @model.federails_actor
  end

  def before_template
    @editable = policy(@model).edit?
  end

  def view_template
    div(class: "tw:relative tw:flex tw:flex-col tw:rounded-xl tw:overflow-hidden tw:bg-white tw:dark:bg-secondary-800 tw:shadow-sm tw:hover:shadow-md tw:transition-shadow tw:mb-3") do
      div(class: "tw:absolute tw:top-0 tw:left-0 tw:right-0 tw:z-10 tw:px-2 tw:py-1 tw:bg-secondary-200/90 tw:dark:bg-secondary-700/90 tw:text-sm") { server_indicator @model } if @model.remote?
      div(class: "tw:relative tw:w-full tw:aspect-[4/3]") do
        selection_bubble if @editable
        if @actor && !@actor.local
          PreviewFrame(object: @model)
        else
          link_to @model, class: "tw:block tw:no-underline", data: {turbo_frame: "_top"}, aria: {label: translate("components.model_card.open_button.label", name: @model.name)} do
            PreviewFrame(object: @model)
          end
        end
      end
      div(class: "tw:p-3 tw:flex tw:flex-col tw:gap-1") { info_row }
      actions
    end
  end

  private

  def title
    div(class: "tw:font-medium tw:text-secondary-900 tw:dark:text-secondary-100") do
      if @editable
        EditableSpan(fieldname: "model[name]", path: model_path(@model), text: @model.name)
      else
        link_to @model.name, @model, class: "tw:text-inherit tw:no-underline hover:tw:underline", data: {turbo_frame: "_top"}, "aria-label": translate("components.model_card.open_button.label", name: @model.name)
      end
      if @model.sensitive
        whitespace
        Icon(icon: "explicit", label: Model.human_attribute_name(:sensitive))
      end
      whitespace
      AccessIndicator(object: @model)
    end
  end

  def open_button
    link_class = "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-2 tw:py-1 tw:text-sm tw:font-medium tw:rounded-lg tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2 tw:bg-primary-600 tw:text-white tw:hover:bg-primary-700"
    link_opts = {class: link_class, "aria-label": translate("components.model_card.open_button.label", name: @model.name), data: {turbo_frame: "_top"}}
    if @actor && !@actor.local
      link_to @actor.profile_url, link_opts do
        span { "⁂" }
        whitespace
        span { t("components.model_card.open_button.text") }
      end
    else
      link_to t("components.model_card.open_button.text"), @model, link_opts
    end
  end

  def credits
    ul(class: "tw:list-none tw:flex tw:flex-wrap tw:gap-x-2 tw:text-xs tw:text-secondary-500 tw:dark:text-secondary-400 tw:m-0 tw:p-0") do
      if @actor && !@actor.local
        if (creator = @actor.extensions["attributedTo"])
          li { creator target: creator["url"], name: creator["name"] }
        end
        if (collection = @actor.extensions["context"])
          li { collection target: collection["url"], name: collection["name"] }
        end
      else
        li { creator target: @model.creator, name: @model.creator.name } if @model.creator
        li { collection target: @model.collection, name: @model.collection.name } if @model.collection
      end
    end
  end

  def creator(target:, name:)
    Icon icon: "person", label: Creator.model_name.human
    whitespace
    link_to name, target, "aria-label": [Creator.model_name.human, name].join(": "), data: {turbo_frame: "_top"}
  end

  def collection(target:, name:)
    Icon icon: "collection", label: Collection.model_name.human
    whitespace
    link_to name, target, "aria-label": [Collection.model_name.human, name].join(": "), data: {turbo_frame: "_top"}
  end

  def selection_bubble
    button type: "button",
      class: "model-card-selection-bubble tw:absolute tw:top-2 tw:left-2 tw:z-20 tw:w-8 tw:h-8 tw:min-w-[44px] tw:min-h-[44px] tw:rounded-full tw:border-2 tw:border-white tw:bg-secondary-200/80 tw:dark:bg-secondary-700/80 tw:p-0 tw:flex tw:items-center tw:justify-center tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2",
      data: {model_id: @model.public_id, action: "click->model-list-selection#toggle", model_list_selection_target: "bubble"},
      aria: {label: t("models.list.selection.select"), pressed: "false"} do
      span(class: "tw:inline-flex tw:items-center tw:justify-center") do
        Icon(icon: "check2", label: "")
      end
    end
  end

  def caption
    if (summary = @model.try(:caption) || @actor.extensions&.dig("summary"))
      span(class: "tw:text-sm tw:text-secondary-500 tw:dark:text-secondary-400") do
        sanitize summary.split("</p>", 2).first
      end
    end
  end

  def info_row
    div(class: "tw:flex tw:flex-wrap tw:items-start tw:gap-x-2 tw:gap-y-1") do
      div(class: "tw:min-w-0 tw:flex-1") do
        title
        caption
      end
      div(class: "tw:flex-shrink-0") do
        small { credits }
      end
    end
  end

  def actions
    div(class: "tw:px-3 tw:py-2 tw:border-t tw:border-secondary-200 tw:dark:border-secondary-600") do
      div(class: "tw:flex tw:flex-wrap tw:items-center tw:gap-2") do
        div(class: "tw:min-w-0 tw:flex-1") do
          open_button
          whitespace
          StatusBadges model: @model
        end
        div(class: "tw:flex-shrink-0") do
          BurgerMenu(small: true) do
            DropdownItem(icon: "pencil", label: t("components.model_card.edit_button.text"), path: edit_model_path(@model), aria_label: translate("components.model_card.edit_button.label", name: @model.name), turbo_frame: "_top") if policy(@model).edit?
            DropdownItem(icon: "trash", label: t("components.model_card.delete_button.text"), path: model_path(@model), method: :delete, aria_label: translate("components.model_card.delete_button.label", name: @model.name), confirm: translate("models.destroy.confirm"), turbo_frame: "_top") if policy(@model).destroy?
            DropdownItem(icon: "flag", label: t("general.report", type: ""), path: new_model_report_path(@model), turbo_frame: "_top") if SiteSettings.multiuser_enabled?
          end
        end
      end
    end
  end
end
