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
    # INIT-017/SPEC-003 — morph reconnect so Tom Select survives Turbo morph
    raw @form.select( # rubocop:disable Rails/OutputSafety
      @attribute,
      @select_options,
      @options.except(:button, :select_id).compact,
      {
        data: {
          controller: "searchable-select",
          action: "turbo:morph@window->searchable-select#reconnect"
        },
        class: select_class,
        id: select_dom_id
      }
    )
    if @options[:button]
      render_association_button(@options[:button])
    end
  end

  private

  def select_dom_id
    @options[:select_id].presence || "#{@form.object_name}_#{@attribute}"
  end

  def render_association_button(button)
    classes = "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 bg-white border border-primary-500 text-primary-700 hover:bg-primary-50 dark:bg-secondary-800 dark:border-primary-500 dark:text-primary-300 dark:hover:bg-secondary-700 ml-2 shrink-0"
    if button[:dialog].present?
      button(
        type: "button",
        class: classes,
        data: {action: "click->dialog#open", dialog_id: button[:dialog]},
        aria: {haspopup: "dialog"}
      ) { button[:label] }
    else
      a(href: button[:path], class: classes) { button[:label] }
    end
  end
end
