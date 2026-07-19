# frozen_string_literal: true

class Components::CheckBoxInputRow < Components::InputRow
  # Two-cell layout for .tabular-form (label | control). Do not put both in one cell —
  # that leaves the value column empty and hides the checkbox on sm+.
  def view_template
    div do
      @form.label(@attribute, @label, class: label_class)
    end
    div(class: "mt-1") do
      @form.check_box(
        @attribute,
        {
          class: "rounded border-secondary-300 dark:border-secondary-400 dark:bg-secondary-800 text-primary-600 focus:ring-2 focus:ring-primary-500 h-5 w-5"
        }.merge(@options)
      )
      errors_for(@form.object, @attribute_without_id)
      help
    end
  end
end
