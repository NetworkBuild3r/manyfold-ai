# Define an application-wide content security policy.
# See the Securing Rails Applications Guide for more information:
# https://guides.rubyonrails.org/security.html#content-security-policy-header

# Configured dynamically in ApplicationController#configure_content_security_policy

Rails.application.configure do
  # Disable CSP nonce if we're pulling in Scout DevTrace
  unless Rails.env.development? && ENV.fetch("SCOUT_DEV_TRACE", false) === "true"
    # Prefer a per-request random nonce. session.id is often blank (especially
    # before the session cookie is established), which produced CSP values like
    # script-src 'nonce-' and blocked inline boot scripts once Traefik stopped
    # injecting style/script unsafe-inline for this app.
    config.content_security_policy_nonce_generator = ->(request) {
      request.env["manyfold.csp_nonce"] ||= SecureRandom.base64(16)
    }
  end
end
