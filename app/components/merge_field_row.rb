# frozen_string_literal: true

# A/B radio pair plus optional override, matching the Print Studio merge modal.
class Components::MergeFieldRow < Components::Base
  def initialize(field:, label:, value_a:, value_b:, kind: :text, default: "a", override: true)
    @field = field
    @label = label
    @value_a = value_a
    @value_b = value_b
    @kind = kind
    @default = default
    @override = override
  end

  def view_template
    div(class: "flex flex-col gap-2") do
      p(class: "text-[11px] font-medium uppercase tracking-wide text-secondary-500 dark:text-secondary-400 m-0") { @label }
      div(class: "grid grid-cols-1 sm:grid-cols-2 gap-2") do
        choice_card("a", @value_a)
        choice_card("b", @value_b)
      end
      override_input if @override && @kind != :preview && @kind != :readonly
    end
  end

  private

  def choice_card(side, value)
    label(class: "flex items-start gap-2 p-3 rounded-md border border-secondary-200 dark:border-secondary-600 bg-white dark:bg-secondary-900 cursor-pointer has-[:checked]:border-primary-500") do
      unless @kind == :readonly
        input(
          type: "radio",
          name: "fields[#{@field}]",
          value: side,
          checked: @default == side,
          class: "mt-0.5 border-secondary-300 text-primary-600 focus:ring-primary-500"
        )
      end
      div(class: "min-w-0 flex-1 text-sm text-secondary-800 dark:text-secondary-100") do
        if @kind == :preview && value.is_a?(Hash)
          preview_card(value)
        else
          span(class: (@kind == :textarea) ? "whitespace-pre-wrap break-words" : "break-words") { display(value) }
        end
      end
    end
  end

  def preview_card(value)
    p(class: "text-xs text-secondary-500 m-0 mb-2") { value[:caption] }
    if value[:src]
      img(src: value[:src], alt: value[:caption], class: "w-full h-20 object-cover rounded", width: 200, height: 80)
    else
      span(class: "text-secondary-400") { t("problems.merge.none") }
    end
  end

  def override_input
    attrs = {
      name: "overrides[#{@field}]",
      placeholder: t("problems.merge.override", field: @label.downcase),
      autocomplete: "off",
      data: {action: "input->duplicate-merge#pickOverride", merge_field: @field},
      class: "w-full rounded-md border border-secondary-300 dark:border-secondary-600 bg-white dark:bg-secondary-950 px-3 py-2 text-sm text-secondary-800 dark:text-secondary-100 placeholder:text-secondary-400 focus:ring-2 focus:ring-primary-500"
    }
    if @kind == :textarea
      textarea(**attrs, rows: 3)
    else
      input(type: "text", **attrs)
    end
  end

  def display(value)
    text = value.to_s.strip
    text.presence || t("problems.merge.none")
  end
end
