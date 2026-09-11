# frozen_string_literal: true

# INIT-028/SPEC-002 — D-1 / D-9: civil theme from user overlay, then instance, else system.
# Caller passes user; this module never reads current_user.
module ThemeResolver
  def self.call(user: nil, site_theme: nil)
    overlay = user&.interface_theme
    return overlay if allowed?(overlay)

    instance = site_theme.nil? ? SiteSettings.validated_theme : site_theme
    return instance if allowed?(instance)

    "system"
  end

  def self.allowed?(value)
    SiteSettings::AVAILABLE_THEMES.include?(value)
  end
  private_class_method :allowed?
end
