# frozen_string_literal: true

class Components::CheckBoxInputRow < Components::InputRow
  def view_template
    div(class: "flex items-center gap-2") do
      input_element
      @form.label(@attribute, @label, class: "text-sm text-secondary-700 dark:text-secondary-300 cursor-pointer")
    end
    div(class: "mt-1") do
      errors_for(@form.object, @attribute_without_id)
      help
    end
  end

  def input_element
    @form.check_box(
      @attribute,
      {
        class: "rounded border-secondary-300 text-primary-600 focus:ring-2 focus:ring-primary-500 h-4 w-4"
      }.merge(@options)
    )
  end

  def label_class
    nil
  end
end
