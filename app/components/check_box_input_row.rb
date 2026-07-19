# frozen_string_literal: true

class Components::CheckBoxInputRow < Components::InputRow
  # Two-cell layout for .tabular-form (label | control).
  # Must `raw` the Rails form HTML — Phlex ignores non-last block return values,
  # which left an empty value cell (label only, no checkbox).
  def view_template
    div do
      raw @form.label(@attribute, @label, class: label_class) # rubocop:disable Rails/OutputSafety
    end
    div(class: "mt-1 flex items-center gap-2") do
      raw @form.check_box( # rubocop:disable Rails/OutputSafety
        @attribute,
        {
          class: [
            "h-5 w-5 shrink-0 rounded border-2",
            "border-secondary-400 bg-white text-primary-600",
            "focus:ring-2 focus:ring-primary-500",
            "dark:border-secondary-300 dark:bg-secondary-700 dark:checked:bg-primary-500"
          ].join(" ")
        }.merge(@options)
      )
      errors_for(@form.object, @attribute_without_id)
      help
    end
  end
end
