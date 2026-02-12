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
    div class: "col mb-3" do
      div class: "card preview-card" do
        div(class: "card-header position-absolute w-100 top-0 z-3 bg-body-secondary text-secondary-emphasis opacity-75") { server_indicator @model } if @model.remote?
        div class: "position-relative" do
          selection_bubble if @editable
          if @actor && !@actor.local
            PreviewFrame(object: @model)
          else
            link_to @model, class: "text-decoration-none d-block", data: {turbo_frame: "_top"}, aria: {label: translate("components.model_card.open_button.label", name: @model.name)} do
              PreviewFrame(object: @model)
            end
          end
        end
        div(class: "card-body") { info_row }
        actions
      end
    end
  end

  private

  def title
    div class: "card-title" do
      if @editable
        EditableSpan(fieldname: "model[name]", path: model_path(@model), text: @model.name)
      else
        link_to @model.name, @model, class: "text-body text-decoration-none", data: {turbo_frame: "_top"}, "aria-label": translate("components.model_card.open_button.label", name: @model.name)
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
    link_opts = {class: "btn btn-primary btn-sm", "aria-label": translate("components.model_card.open_button.label", name: @model.name), data: {turbo_frame: "_top"}}
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
    ul class: "list-unstyled" do
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
      class: "model-card-selection-bubble position-absolute top-0 start-0 m-2 rounded-circle border border-2 border-white bg-body-secondary bg-opacity-75 p-0",
      data: {model_id: @model.public_id, action: "click->model-list-selection#toggle", model_list_selection_target: "bubble"},
      aria: {label: t("models.list.selection.select"), pressed: "false"} do
      span(class: "model-card-selection-check d-inline-flex align-items-center justify-content-center") do
        Icon(icon: "check2", label: "")
      end
    end
  end

  def caption
    if (summary = @model.try(:caption) || @actor.extensions&.dig("summary"))
      span class: "card-subtitle text-muted" do
        sanitize summary.split("</p>", 2).first
      end
    end
  end

  def info_row
    div class: "row" do
      div class: "col" do
        title
        caption
      end
      div class: "col-auto" do
        small do
          credits
        end
      end
    end
  end

  def actions
    div class: "card-footer" do
      div class: "row" do
        div class: "col" do
          open_button
          whitespace
          StatusBadges model: @model
        end
        div class: "col col-auto" do
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
