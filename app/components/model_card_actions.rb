# frozen_string_literal: true

class Components::ModelCardActions < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  register_value_helper :policy

  def initialize(model:, editable:, actor: nil)
    @model = model
    @editable = editable
    @actor = actor || model.federails_actor
  end

  def view_template
    div(class: "px-3 py-2 border-t border-secondary-200 dark:border-secondary-600") do
      div(class: "flex flex-wrap items-center gap-2") do
        div(class: "min-w-0 flex-1") do
          open_button
          whitespace
          StatusBadges model: @model
        end
        div(class: "flex-shrink-0") do
          BurgerMenu(small: true) do
            DropdownItem(icon: "pencil", label: t("components.model_card.edit_button.text"), path: edit_model_path(@model), aria_label: translate("components.model_card.edit_button.label", name: @model.name), turbo_frame: "_top") if policy(@model).edit?
            DropdownItem(icon: "trash", label: t("components.model_card.delete_button.text"), path: model_path(@model), method: :delete, aria_label: translate("components.model_card.delete_button.label", name: @model.name), confirm: translate("models.destroy.confirm"), turbo_frame: "_top") if policy(@model).destroy?
            DropdownItem(icon: "flag", label: t("general.report", type: ""), path: new_model_report_path(@model), turbo_frame: "_top") if SiteSettings.multiuser_enabled?
          end
        end
      end
    end
  end

  private

  def open_button
    link_class = [Components::BaseButton::BASE_CLASSES, Components::BaseButton::VARIANT_CLASSES["primary"], "px-2 py-1"].join(" ")
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
end
