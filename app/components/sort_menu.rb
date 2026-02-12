# frozen_string_literal: true

class Components::SortMenu < Components::Base
  register_value_helper :session

  def initialize(filter: {})
    @filter = filter
  end

  def view_template
    div(class: "tw:relative", data: {controller: "dropdown"}) do
      button type: "button",
        data: {action: "click->dropdown#toggle"},
        aria: {expanded: "false", haspopup: "menu"},
        class: "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-lg tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2 tw:bg-white tw:border tw:border-secondary-300 tw:hover:bg-secondary-50 tw:dark:bg-secondary-800 tw:dark:border-secondary-600 tw:dark:hover:bg-secondary-700" do
        Icon(icon: "sort-down")
        whitespace
        span { t "components.sort_menu.sort-by" }
      end
      ul class: "tw:absolute tw:left-0 tw:mt-1 tw:min-w-[10rem] tw:py-1 tw:bg-white tw:dark:bg-secondary-800 tw:rounded-lg tw:shadow-lg tw:border tw:border-secondary-200 tw:dark:border-secondary-600 tw:z-50",
        data: {dropdown_target: "menu"},
        role: "menu" do
        item "sort-alpha-down", "name", "asc" # i18n-tasks-use t('components.sort_menu.name')
        item "sort-numeric-down-alt", "recent", "desc" # i18n-tasks-use t('components.sort_menu.recent')
        item "sort-numeric-down-alt", "updated", "desc" # i18n-tasks-use t('components.sort_menu.updated')
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
