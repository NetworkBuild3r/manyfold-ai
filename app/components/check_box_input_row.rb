# frozen_string_literal: true

class Components::CheckBoxInputRow < Components::InputRow
  def view_template
    div(class: "tw:flex tw:items-center tw:gap-2") do
      input_element
      @form.label(@attribute, @label, class: "tw:text-sm tw:text-secondary-700 tw:dark:text-secondary-300 tw:cursor-pointer")
    end
    div(class: "tw:mt-1") do
      errors_for(@form.object, @attribute_without_id)
      help
    end
  end

  def input_element
    @form.check_box(
      @attribute,
      {
        class: "tw:rounded tw:border-secondary-300 tw:text-primary-600 tw:focus:ring-primary-500 tw:h-4 tw:w-4"
      }.merge(@options)
    )
  end

  def label_class
    nil
  end
end
