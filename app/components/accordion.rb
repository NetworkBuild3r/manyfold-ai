# frozen_string_literal: true

class Components::Accordion < Components::Base
  def initialize(title:, open: false, id: SecureRandom.uuid)
    @title = title
    @open = open
    @id = id
  end

  def view_template
    div(class: "tw:border tw:border-secondary-200 tw:dark:border-secondary-600 tw:rounded-lg tw:overflow-hidden tw:mb-2", data: {controller: "collapse"}) do
      div(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 last:tw:border-b-0") do
        h3(class: "tw:m-0") do
          button type: "button",
            class: "tw:w-full tw:flex tw:items-center tw:justify-between tw:px-4 tw:py-3 tw:text-left tw:font-medium tw:bg-secondary-50 tw:dark:bg-secondary-800/50 tw:hover:bg-secondary-100 tw:dark:hover:bg-secondary-700/50 tw:border-0 tw:cursor-pointer tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-inset #{'tw:rounded-t-lg' unless @open}",
            data: {action: "click->collapse#toggle"},
            aria: {controls: @id, expanded: @open} do
            span { @title }
            span(class: "tw:transition-transform tw:duration-200 #{'tw:rotate-180' if @open}") do
              Icon(icon: "chevron-down", label: @open ? t("general.collapse") : t("general.expand"))
            end
          end
        end
      end
      div id: @id,
        class: "tw:px-4 tw:py-3 tw:bg-white tw:dark:bg-secondary-800 #{'show' if @open}",
        data: {collapse_target: "content"} do
        yield
      end
    end
  end
end
