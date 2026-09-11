# frozen_string_literal: true

# INIT-027/SPEC-006 — file field chrome uses TextInputRow::INPUT_CLASS (no drifted copy).
class Components::FileInputRow < Components::InputRow
  def initialize(form:, attribute:, label: nil, help: nil, options: {}, remove: false, remove_label: nil)
    @remove = remove
    @remove_label = remove_label
    super(form: form, attribute: attribute, label: label, help: help, options: options)
  end

  def input_group
    div(class: "flex gap-2 items-center") do
      input_element
      remove_control
    end
  end

  def input_element
    raw @form.file_field(@attribute, {class: Components::TextInputRow::INPUT_CLASS}.merge(@options)) # rubocop:disable Rails/OutputSafety
  end

  private

  def remove_control
    return unless @remove

    raw @form.check_box( # rubocop:disable Rails/OutputSafety
      :"remove_#{@attribute}",
      class: "rounded border-secondary-300 text-primary-600 focus:ring-primary-500 h-4 w-4",
      autocomplete: "off"
    )
    icon_html = Components::Icon.new(icon: "trash", label: @remove_label).call
    raw @form.label( # rubocop:disable Rails/OutputSafety
      :"remove_#{@attribute}",
      icon_html,
      class: [
        Components::BaseButton::BASE_CLASSES,
        Components::BaseButton::VARIANT_CLASSES.fetch("outline-danger"),
        "cursor-pointer"
      ].join(" ")
    )
  end
end
