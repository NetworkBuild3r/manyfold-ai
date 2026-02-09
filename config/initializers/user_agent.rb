version = Rails.application.config.app_version.to_s.tr("v", "").presence || "unknown"
Faraday.default_connection_options.headers = {"User-Agent" => "Manyfold/#{version}"}
