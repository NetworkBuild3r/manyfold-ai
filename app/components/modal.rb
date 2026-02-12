# frozen_string_literal: true

class Components::Modal < Components::Base
  def initialize(id:, title:)
    @id = id
    @title = title
  end

  def view_template
    dialog class: "tw:relative tw:max-w-2xl tw:w-full tw:max-h-[90vh] tw:overflow-auto tw:rounded-xl tw:bg-white tw:dark:bg-secondary-800 tw:shadow-xl tw:p-0 tw:border-0",
           id: @id,
           "aria-labelledby": "#{@id}-label",
           "aria-modal": "true",
           data: {dialog_target: "dialog"} do
      div(class: "tw:p-4 tw:sm:p-6") do
        div(class: "tw:flex tw:items-center tw:justify-between tw:gap-4 tw:mb-4") do
          h1(class: "tw:text-lg tw:font-semibold tw:text-secondary-900 tw:dark:text-secondary-100 tw:m-0", id: "#{@id}-label") { @title }
          button type: "button",
            class: "tw:rounded-full tw:p-1 tw:hover:bg-secondary-100 tw:dark:hover:bg-secondary-700 focus:tw:outline-none tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500",
            data: {action: "click->dialog#close"},
            "aria-label": t("components.modal.close") do
            Icon(icon: "x-lg", label: t("components.modal.close"))
          end
        end
        div(class: "tw:prose tw:max-w-none tw:dark:prose-invert") do
          yield
        end
      end
    end
  end
end
