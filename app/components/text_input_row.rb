# frozen_string_literal: true

class Components::TextInputRow < Components::InputRow
  INPUT_CLASS = "block w-full rounded-lg border border-secondary-300 bg-white text-secondary-900 px-3 py-2 shadow-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 dark:border-secondary-500 dark:bg-secondary-800 dark:text-secondary-100"

  def input_element
    raw @form.text_field(@attribute, {class: INPUT_CLASS}.merge(@options)) # rubocop:disable Rails/OutputSafety
  end
end
