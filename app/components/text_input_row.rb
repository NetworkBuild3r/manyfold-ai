# frozen_string_literal: true

class Components::TextInputRow < Components::InputRow
  INPUT_CLASS = "tw:block tw:w-full tw:rounded-lg tw:border tw:border-secondary-300 tw:px-3 tw:py-2 tw:shadow-sm tw:focus:ring-2 tw:focus:ring-primary-500 tw:focus:border-primary-500 tw:dark:border-secondary-600 tw:dark:bg-secondary-800".freeze

  def input_element
    @form.text_field(@attribute, {class: INPUT_CLASS}.merge(@options))
  end
end
