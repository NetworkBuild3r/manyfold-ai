# frozen_string_literal: true

class Components::CopyableText < Components::Base
  def initialize(text:, label: nil, obfuscated: false)
    @text = text
    @label = label
    @obfuscated = obfuscated
  end

  def before_template
    @label ||= t("components.copy_button.copy")
  end

  def view_template
    btn_class = "tw:inline-flex tw:items-center tw:justify-center tw:px-2 tw:py-1 tw:text-sm tw:font-medium tw:rounded tw:border tw:border-secondary-300 tw:bg-white tw:dark:bg-secondary-800 tw:hover:bg-secondary-50 tw:dark:hover:bg-secondary-700 tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500"
    div(class: "tw:inline-flex tw:items-center tw:gap-1 tw:flex-wrap", data: {controller: "obfuscated-text"}) do
      span(class: (@obfuscated ? "obfuscated" : nil)) { @text }
      whitespace
      if @obfuscated
        button class: btn_class, title: t("components.copyable_text.reveal"), data: {action: "click->obfuscated-text#toggle:prevent"} do
          Icon icon: "eye", label: t("components.copyable_text.reveal")
        end
        whitespace
      end
      button class: btn_class, title: @label, data: {controller: "copy-text", action: "click->copy-text#copy:prevent", copy_text_text_value: @text} do
        Icon icon: "clipboard-plus", label: @label
      end
    end
  end
end
