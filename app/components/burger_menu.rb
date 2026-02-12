# frozen_string_literal: true

class Components::BurgerMenu < Components::Base
  def initialize(small: false, direction: :down, id: SecureRandom.uuid, data: {})
    @small = small
    @id = id
    @data = data
    @direction = direction
  end

  def view_template
    trigger_class = "tw:inline-flex tw:items-center tw:justify-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-lg tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2 tw:bg-white tw:border tw:border-secondary-300 tw:hover:bg-secondary-50 tw:dark:bg-secondary-800 tw:dark:border-secondary-600 tw:dark:hover:bg-secondary-700 tw:min-w-[44px] tw:min-h-[44px]"
    trigger_class += " tw:px-2 tw:py-1" if @small
    div id: @id,
        data: @data.merge(controller: "dropdown"),
        class: "tw:relative" do
      a id: "#{@id}-anchor",
        href: "#",
        data: {action: "click->dropdown#toggle"},
        aria: {
          expanded: false,
          haspopup: "menu",
          controls: "#{@id}-menu"
        },
        class: trigger_class,
        tabindex: 0 do
        Icon icon: "list", label: t("general.menu")
      end
      ul class: burger_menu_ul_class,
        id: "#{@id}-menu",
        data: {dropdown_target: "menu"},
        role: "menu",
        aria: {labelledby: "#{@id}-anchor"} do
        yield
      end
    end
  end

  private

  def burger_menu_ul_class
    base = "tw:absolute tw:right-0 tw:min-w-[10rem] tw:py-1 tw:bg-white tw:dark:bg-secondary-800 tw:rounded-lg tw:shadow-lg tw:border tw:border-secondary-200 tw:dark:border-secondary-600 tw:z-50"
    @direction == :up ? "#{base} tw:bottom-full tw:mb-1" : "#{base} tw:mt-1"
  end
end
