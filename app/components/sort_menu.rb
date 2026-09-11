# frozen_string_literal: true

class Components::SortMenu < Components::Base
  # INIT-027/SPEC-007 — trigger uses VARIANT_CLASSES["toolbar"], not an inlined BASE_CLASSES prefix.
  register_value_helper :session

  def initialize(filter: {})
    @filter = filter
  end

  def view_template
    # align right: sort control sits on the trailing edge of the list toolbar;
    # left-aligned menus were clipped by the sidebar.
    div(class: "relative z-30", data: {controller: "dropdown"}) do
      button type: "button",
        data: {action: "click->dropdown#toggle"},
        aria: {expanded: "false", haspopup: "menu"},
        class: Components::BaseButton::VARIANT_CLASSES.fetch("toolbar") do
        Icon(icon: "sort-down")
        whitespace
        span { t "components.sort_menu.sort-by" }
      end
      ul class: "#{Components::DropdownMenu.panel_class(align: :right, direction: :down)} z-[100]",
        data: {dropdown_target: "menu"},
        role: "menu" do
        item "sort-alpha-down", "name", "asc" # i18n-tasks-use t('components.sort_menu.name')
        item "sort-numeric-down-alt", "recent", "desc" # i18n-tasks-use t('components.sort_menu.recent')
        item "sort-numeric-down-alt", "updated", "desc" # i18n-tasks-use t('components.sort_menu.updated')
        item "shuffle", "random", "asc" # i18n-tasks-use t('components.sort_menu.random')
      end
    end
  end

  def ordering_by?(order)
    if current_user
      current_user.sort_order == order
    else
      session["order"] == order
    end
  end

  def ordered_url(order, direction)
    url_for({order: order, direction: direction}.merge(@filter&.to_params))
  end

  def item(icon, key, direction)
    DropdownItem icon: icon, label: t("components.sort_menu.%{key}" % {key: key}), path: ordered_url(key, direction), active: ordering_by?(key)
  end
end
