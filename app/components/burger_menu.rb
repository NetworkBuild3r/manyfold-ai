# frozen_string_literal: true

class Components::BurgerMenu < Components::Base
  def initialize(small: false, direction: :down, id: SecureRandom.uuid, data: {})
    @small = small
    @id = id
    @data = data
    @direction = direction
  end

  def view_template
    trigger_class = "inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 bg-white border border-secondary-300 hover:bg-secondary-50 dark:bg-secondary-800 dark:border-secondary-600 dark:hover:bg-secondary-700 min-w-[44px] min-h-[44px]"
    trigger_class += " px-2 py-1" if @small
    div id: @id,
      data: @data.merge(controller: "dropdown"),
      class: "relative" do
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
      ul class: Components::DropdownMenu.panel_class(align: :right, direction: @direction),
        id: "#{@id}-menu",
        data: {dropdown_target: "menu"},
        role: "menu",
        aria: {labelledby: "#{@id}-anchor"} do
        yield
      end
    end
  end
end
