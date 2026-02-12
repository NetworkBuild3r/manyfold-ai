# frozen_string_literal: true

class Components::SelectInputRow < Components::InputRow
  def initialize(form:, attribute:, label:, select_options:, help: nil, options: {})
    @select_options = select_options
    super(form: form, attribute: attribute, label: label, help: help, options: options)
  end

  def input_element
    invalid = @form.object&.errors&.include?(@attribute_without_id) && @form.object.errors[@attribute_without_id].present?
    select_class = Components::TextInputRow::INPUT_CLASS.dup
    select_class += " tw:border-danger" if invalid
    raw @form.select( # rubocop:disable Rails/OutputSafety
      @attribute,
      @select_options,
      @options.compact,
      {
        data: {
          controller: "searchable-select"
        },
        class: select_class
      }
    )
    if @options[:button]
      a href: @options[:button][:path], class: "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-lg tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2 tw:bg-white tw:border tw:border-secondary-300 tw:hover:bg-secondary-50 tw:dark:bg-secondary-800 tw:dark:border-secondary-600 tw:dark:hover:bg-secondary-700 tw:ml-2" do
        @options[:button][:label]
      end
    end
  end
end
