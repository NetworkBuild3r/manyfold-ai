# Session cookie lifetime. SESSION_EXPIRE_DAYS (default 14). Personal: set e.g. 3650.
Rails.application.config.session_store :cookie_store,
  expire_after: ENV.fetch("SESSION_EXPIRE_DAYS", "14").to_i.days,
  key: "_manyfold_session",
  same_site: :lax,
  secure: Rails.application.config.force_ssl
