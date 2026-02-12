# frozen_string_literal: true

class Components::BaseButton < Components::Base
  include Phlex::Rails::Helpers::ButtonTo

  BASE_CLASSES = "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-lg tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2".freeze

  VARIANT_CLASSES = {
    "primary" => "tw:bg-primary-600 tw:text-white tw:hover:bg-primary-700",
    "secondary" => "tw:bg-white tw:border tw:border-secondary-300 tw:hover:bg-secondary-50 tw:dark:bg-secondary-800 tw:dark:border-secondary-600 tw:dark:hover:bg-secondary-700",
    "danger" => "tw:bg-danger tw:text-white tw:hover:opacity-90",
    "warning" => "tw:bg-warning tw:text-secondary-900 tw:hover:opacity-90",
    "outline-primary" => "tw:bg-transparent tw:border tw:border-primary-600 tw:text-primary-600 tw:hover:bg-primary-50 tw:dark:hover:bg-primary-900/30",
    "outline-secondary" => "tw:bg-transparent tw:border tw:border-secondary-300 tw:text-secondary-700 tw:hover:bg-secondary-50 tw:dark:border-secondary-600 tw:dark:text-secondary-300 tw:dark:hover:bg-secondary-800",
    "outline-danger" => "tw:bg-transparent tw:border tw:border-danger tw:text-danger tw:hover:bg-danger/10",
    "outline-warning" => "tw:bg-transparent tw:border tw:border-warning tw:text-warning tw:hover:bg-warning/10"
  }.freeze

  def initialize(label:, href:, variant:, icon: nil, method: nil, icon_only: false, aria_label: nil, confirm: nil, data: {}, nofollow: nil, target: nil)
    @icon = icon
    @label = label
    @href = href
    @variant = variant.to_s
    @method = method
    @icon_only = icon_only
    @aria_label = aria_label
    @confirm = confirm
    @data = data
    @nofollow = nofollow
    @target = target
  end

  def view_template
    helper(
      @href,
      method: @method,
      class: button_class,
      rel: (@nofollow ? "nofollow" : nil),
      aria: {label: @aria_label || (@icon_only ? @label : nil)},
      data: {confirm: @confirm}.merge(@data),
      target: @target
    ) do
      if @icon
        Icon(icon: @icon, label: @label)
        whitespace
      end
      span(class: (@icon_only ? "tw:sr-only" : nil)) { @label }
    end
  end

  def helper(*args)
    raise NotImplementedError
  end

  private

  def button_class
    variant_classes = VARIANT_CLASSES[@variant] || VARIANT_CLASSES["secondary"]
    [BASE_CLASSES, variant_classes].join(" ")
  end
end
