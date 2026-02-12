# frozen_string_literal: true

class Components::NumericInputRow < Components::InputRow
  def initialize(form:, attribute:, label:, unit: nil, help: nil, options: {})
    @unit = unit
    super(form: form, attribute: attribute, label: label, help: help, options: options)
  end

  def input_element
    input_class = Components::TextInputRow::INPUT_CLASS.dup
    input_class += " tw:rounded-r-none" if @unit
    raw @form.number_field(@attribute, {class: input_class}.merge(@options)) # rubocop:disable Rails/OutputSafety
    if @unit
      span(class: "tw:inline-flex tw:items-center tw:px-3 tw:py-2 tw:border tw:border-secondary-300 tw:border-l-0 tw:rounded-r-lg tw:bg-secondary-50 tw:dark:bg-secondary-800 tw:text-sm tw:text-secondary-600 tw:dark:text-secondary-400") { @unit }
    end
  end
end
