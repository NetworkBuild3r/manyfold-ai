# frozen_string_literal: true

class Components::DropdownItem < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  def initialize(label:, path:, icon: nil, method: nil, aria_label: nil, confirm: nil, active: false, turbo_frame: nil)
    @icon = icon
    @label = label
    @path = path
    @method = method
    @aria_label = aria_label
    @confirm = confirm
    @active = active
    @turbo_frame = turbo_frame
  end

  def view_template
    li role: "presentation" do
      link_to @path,
        method: @method,
        class: dropdown_item_class,
        role: "menuitem",
        aria: {label: @aria_label, current: @active ? "true" : nil},
        data: {confirm: @confirm, turbo_frame: @turbo_frame}.compact,
        rel: "nofollow" do
        if @icon
          Icon(icon: @icon, label: @label)
          whitespace
        end
        span { @label }
      end
    end
  end

  private

  def dropdown_item_class
    base = "tw:block tw:w-full tw:px-3 tw:py-2 tw:text-left tw:text-sm tw:text-secondary-700 tw:dark:text-secondary-200 tw:hover:bg-secondary-100 tw:dark:hover:bg-secondary-700 tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:no-underline"
    base += " tw:bg-primary-50 tw:dark:bg-primary-900/30 tw:font-medium" if @active
    base
  end
end
