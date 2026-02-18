# frozen_string_literal: true

class Components::Accordion < Components::Base
  def initialize(title:, open: false, id: SecureRandom.uuid)
    @title = title
    @open = open
    @id = id
  end

  def view_template
    div(class: "border border-secondary-200 dark:border-secondary-600 rounded-lg overflow-hidden mb-2", data: {controller: "collapse"}) do
      div(class: "border-b border-secondary-200 dark:border-secondary-600 last:border-b-0") do
        h3(class: "m-0") do
          button type: "button",
            class: "w-full flex items-center justify-between px-4 py-3 text-left font-medium bg-secondary-50 dark:bg-secondary-800/50 hover:bg-secondary-100 dark:hover:bg-secondary-700/50 border-0 cursor-pointer transition-colors focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-inset #{"rounded-t-lg" unless @open}",
            data: {action: "click->collapse#toggle"},
            aria: {controls: @id, expanded: @open} do
            span { @title }
            span(class: "transition-transform duration-200 #{"rotate-180" if @open}") do
              Icon(icon: "chevron-down", label: @open ? t("general.collapse") : t("general.expand"))
            end
          end
        end
      end
      div id: @id,
        class: "px-4 py-3 bg-white dark:bg-secondary-800 #{"show" if @open}",
        data: {collapse_target: "content"} do
        yield
      end
    end
  end
end
