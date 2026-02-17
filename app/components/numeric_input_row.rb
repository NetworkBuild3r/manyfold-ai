# frozen_string_literal: true

class Components::NumericInputRow < Components::InputRow
  def initialize(form:, attribute:, label:, unit: nil, help: nil, options: {})
    @unit = unit
    super(form: form, attribute: attribute, label: label, help: help, options: options)
  end

  def input_element
    input_class = Components::TextInputRow::INPUT_CLASS.dup
    input_class += " rounded-r-none" if @unit
    raw @form.number_field(@attribute, {class: input_class}.merge(@options)) # rubocop:disable Rails/OutputSafety
    if @unit
      span(class: "inline-flex items-center px-3 py-2 border border-secondary-300 border-l-0 rounded-r-lg bg-secondary-50 dark:bg-secondary-800 text-sm text-secondary-600 dark:text-secondary-400") { @unit }
    end
  end
end
