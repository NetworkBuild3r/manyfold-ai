class Components::CopyButton < Components::Base
  def initialize(text:, label: nil)
    @text = text
    @label = label
  end

  def before_template
    @label ||= t("components.copy_button.copy")
  end

  def view_template
    button class: copy_button_class, data: {controller: "copy-text", action: "click->copy-text#copy:prevent", copy_text_text_value: @text} do
      Icon icon: "clipboard-plus", label: @label
    end
  end

  private

  def copy_button_class
    "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-lg tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2 tw:bg-white tw:border tw:border-secondary-300 tw:hover:bg-secondary-50 tw:dark:bg-secondary-800 tw:dark:border-secondary-600 tw:dark:hover:bg-secondary-700"
  end
end
