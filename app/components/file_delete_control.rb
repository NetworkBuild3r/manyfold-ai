# frozen_string_literal: true

# INIT-027/SPEC-010 — one DELETE primitive for file / image / archive-member chrome.
class Components::FileDeleteControl < Components::Base
  def initialize(href:, confirm:, label:, icon: "trash", icon_only: false, variant: "outline-danger", aria_label: nil)
    @href = href
    @confirm = confirm
    @label = label
    @icon = icon
    @icon_only = icon_only
    @variant = variant
    @aria_label = aria_label
  end

  def view_template
    DoButton(
      label: @label,
      href: @href,
      variant: @variant,
      icon: @icon,
      method: :delete,
      icon_only: @icon_only,
      aria_label: @aria_label || @label,
      confirm: @confirm
    )
  end
end
