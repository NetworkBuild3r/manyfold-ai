# frozen_string_literal: true

# INIT-027/SPEC-006 — mutating items are button_to (CSRF form), never link_to method: on <a>.
class Components::DropdownItem < Components::Base
  include Phlex::Rails::Helpers::LinkTo
  include Phlex::Rails::Helpers::ButtonTo

  # INIT-027/SPEC-011 — class channel for specs; initialize/view_template API unchanged.
  ITEM_CLASS = "block w-full px-3 py-2 text-left text-sm text-secondary-700 dark:text-secondary-200 hover:bg-secondary-100 dark:hover:bg-secondary-700 focus-visible:ring-2 focus-visible:ring-primary-500 no-underline"
  ACTIVE_ITEM_CLASS = " bg-primary-50 dark:bg-primary-900/30 font-medium"

  def initialize(label:, path:, icon: nil, method: nil, turbo_method: nil, aria_label: nil, confirm: nil, turbo_confirm: nil, active: false, turbo_frame: nil)
    @icon = icon
    @label = label
    @path = path
    @method = turbo_method || method
    @aria_label = aria_label
    @confirm = turbo_confirm || confirm
    @active = active
    @turbo_frame = turbo_frame
  end

  def view_template
    li role: "presentation" do
      if mutating?
        button_to @path,
          method: @method,
          class: dropdown_item_class,
          form: {class: "w-full m-0"},
          role: "menuitem",
          aria: {label: @aria_label, current: @active ? "true" : nil},
          data: item_data,
          rel: "nofollow" do
          item_body
        end
      else
        link_to @path,
          class: dropdown_item_class,
          role: "menuitem",
          aria: {label: @aria_label, current: @active ? "true" : nil},
          data: item_data,
          rel: "nofollow" do
          item_body
        end
      end
    end
  end

  private

  def mutating?
    @method.present? && @method.to_sym != :get
  end

  def item_data
    attrs = {turbo_frame: @turbo_frame}
    if @confirm.present?
      attrs[:turbo_confirm] = @confirm
      attrs[:confirm] = @confirm
    end
    attrs.compact
  end

  def item_body
    if @icon
      Icon(icon: @icon, label: @label)
      whitespace
    end
    span { @label }
  end

  def dropdown_item_class
    @active ? "#{ITEM_CLASS}#{ACTIVE_ITEM_CLASS}" : ITEM_CLASS
  end
end
