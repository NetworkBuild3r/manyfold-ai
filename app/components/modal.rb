# frozen_string_literal: true

class Components::Modal < Components::Base
  def initialize(id:, title:)
    @id = id
    @title = title
  end

  def view_template
    dialog class: "relative max-w-2xl w-full max-h-[90vh] overflow-auto rounded-xl bg-white dark:bg-secondary-800 shadow-xl p-0 border-0",
      id: @id,
      "aria-labelledby": "#{@id}-label",
      "aria-modal": "true",
      data: {dialog_target: "dialog"} do
      div(class: "p-4 sm:p-6") do
        div(class: "flex items-center justify-between gap-4 mb-4") do
          h1(class: "text-lg font-semibold text-secondary-900 dark:text-secondary-100 m-0", id: "#{@id}-label") { @title }
          button type: "button",
            class: "rounded-full p-1 hover:bg-secondary-100 dark:hover:bg-secondary-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500",
            data: {action: "click->dialog#close"},
            "aria-label": t("components.modal.close") do
            Icon(icon: "x-lg", label: t("components.modal.close"))
          end
        end
        div(class: "prose max-w-none dark:prose-invert") do
          yield
        end
      end
    end
  end
end
