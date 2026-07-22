# frozen_string_literal: true

# Source repository for admin version links (this project, not upstream).
Rails.application.config.source_repo = ENV.fetch("SOURCE_REPO", "https://github.com/NetworkBuild3r/manyfold-ai")
# Back-compat alias used by older templates/specs.
Rails.application.config.upstream_repo = Rails.application.config.source_repo
Rails.application.config.app_version = (ENV.fetch("APP_VERSION", "unknown").to_s.split(":")[-1].presence || "unknown")
Rails.application.config.git_sha = ENV.fetch("GIT_SHA", "main")

if Rails.env.development?
  if File.directory? File.expand_path(".git")
    git_sha = `git rev-parse HEAD`
    git_sha.strip!
    app_version = `git describe --tags --abbrev=0 #{git_sha}`
    app_version.strip!

    Rails.application.config.git_sha = git_sha
    Rails.application.config.app_version = (app_version.presence || Rails.application.config.app_version)
  end
end
