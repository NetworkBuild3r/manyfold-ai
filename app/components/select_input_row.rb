# frozen_string_literal: true

class Components::SelectInputRow < Components::InputRow
  def initialize(form:, attribute:, label:, select_options:, help: nil, options: {})
    @select_options = select_options
    super(form: form, attribute: attribute, label: label, help: help, options: options)
  end

  def input_element
    invalid = @form.object&.errors&.include?(@attribute_without_id) && @form.object.errors[@attribute_without_id].present?
    select_class = Components::TextInputRow::INPUT_CLASS.dup
    select_class += " border-danger" if invalid
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
      a href: @options[:button][:path], class: "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 bg-white border border-secondary-300 hover:bg-secondary-50 dark:bg-secondary-800 dark:border-secondary-600 dark:hover:bg-secondary-700 ml-2" do
        @options[:button][:label]
      end
    end
  end
end
