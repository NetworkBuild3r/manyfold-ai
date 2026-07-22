# RailsSettings Model
class SiteSettings < RailsSettings::Base
  cache_prefix { "v1" }

  field :model_tags_filter_stop_words, type: :boolean, default: true
  field :model_tags_tag_model_directory_name, type: :boolean, default: false
  field :model_tags_stop_words_locale, type: :string, default: "en"
  field :model_tags_custom_stop_words, type: :array, default: SupportedMimeTypes.indexable_extensions
  field :model_tags_auto_tag_new, type: :string, default: "!new"
  field :model_path_template, type: :string, default: "{tags}/{modelName}{modelId}"
  field :model_ignored_files, type: :array, default: [
    /^\.[^.]+/, # Hidden files starting with .
    /.*\/@eaDir\/.*/, # Synology temp files
    /__MACOSX/, # MACOS resource forks
    /^datapackage\.json$/i # Manyfold metadata import/export file
  ]
  field :parse_metadata_from_path, type: :boolean, default: true
  field :safe_folder_names, type: :boolean, default: true
  field :analyse_manifold, type: :boolean, default: false
  field :anonymous_usage_id, type: :string, default: nil
  field :default_viewer_role, type: :string, default: "member"
  field :default_signup_role, type: :string, default: "member"
  field :autocreate_creator_for_new_users, type: :boolean, default: false
  field :approve_signups, type: :boolean, default: true
  field :theme, type: :string, default: "system"
  field :accent_color, type: :string, default: "indigo"
  field :default_library, type: :integer, default: nil
  field :show_libraries, type: :boolean, default: false
  field :registration_enabled, type: :boolean, default: (ENV.fetch("REGISTRATION", nil) == "enabled")

  field :site_name, type: :string, default: ENV.fetch("SITE_NAME", nil)
  field :site_tagline, type: :string, default: ENV.fetch("SITE_TAGLINE", nil)
  field :site_icon, type: :string, default: ENV.fetch("SITE_ICON", nil)
  field :about, type: :string, default: nil
  field :rules, type: :string, default: nil
  field :support_link, type: :string, default: nil

  field :enable_user_quota, type: :boolean, default: false
  field :default_user_quota, type: :integer, default: 0

  field :pregenerate_downloads, type: :boolean, default: false
  field :download_expiry_time_in_hours, type: :integer, default: 24
  field :generate_image_derivatives, type: :boolean, default: false
  # When true, ParseMetadataJob enqueues archive listing for archives outside discovery scans.
  field :scan_archives_on_metadata, type: :boolean, default: false
  field :max_archive_preview_entries, type: :integer, default: 100

  field :allow_robots, type: :boolean, default: false
  field :allow_ai_bots, type: :boolean, default: false
  field :default_indexable, type: :boolean, default: false
  field :default_ai_indexable, type: :boolean, default: false

  field :myminifactory_api_key, type: :string
  field :thingiverse_api_key, type: :string
  field :cults3d_api_key, type: :string
  field :cults3d_api_username, type: :string

  validates :model_ignored_files, regex_array: {strict: true}

  def self.email_configured?
    !Rails.env.production? || ENV.fetch("SMTP_SERVER", false)
  end

  def self.max_file_upload_size
    ENV.fetch("MAX_FILE_UPLOAD_SIZE", 1_073_741_824).to_i
  end

  def self.max_file_extract_size
    ENV.fetch("MAX_FILE_EXTRACT_SIZE", 1_073_741_824).to_i
  end

  def self.demo_mode_enabled?
    Rails.application.config.manyfold_features[:demo_mode]
  end

  def self.multiuser_enabled?
    Rails.application.config.manyfold_features[:multiuser]
  end

  def self.federation_enabled?
    Rails.application.config.manyfold_features[:federation]
  end

  def self.oidc_enabled?
    Rails.application.config.manyfold_features[:oidc]
  end

  def self.default_user
    User.with_role(:administrator).first
  end

  def self.social_enabled?
    multiuser_enabled? || federation_enabled?
  end

  def self.ignored_file?(pathname)
    patterns ||= model_ignored_files
    (File.split(pathname) - ["."]).any? do |path_component|
      patterns.any? { |pattern| path_component =~ pattern.to_regexp }
    end
  end

  def self.fasp_data_sharing_enabled?
    federation_enabled? && FaspClient::Provider.any? { |it| it.has_capability? :account_search }
  end

  AVAILABLE_THEMES = %w[light dark system].freeze
  AVAILABLE_ACCENTS = %w[indigo green purple amber rose].freeze

  LEGACY_DARK_THEMES = %w[cyborg darkly slate solar superhero vapor].freeze

  def self.validated_theme
    return theme if AVAILABLE_THEMES.include?(theme)
    return "dark" if LEGACY_DARK_THEMES.include?(theme)
    "light"
  end

  def self.validated_accent_color
    return accent_color if AVAILABLE_ACCENTS.include?(accent_color)
    "indigo"
  end

  module UserDefaults
    RENDERER = ActiveSupport::HashWithIndifferentAccess.new(
      grid_width: 200,
      grid_depth: 200,
      show_grid: true,
      enable_pan_zoom: false,
      background_colour: "#000000",
      object_colour: "#ffffff",
      render_style: "original",
      # Never auto-load 3D meshes by default. Auto-load on infinite-scroll
      # model cards was the main browser memory bomb (one WebGL worker per card).
      auto_load_max_size: 0
    )

    PAGINATION = ActiveSupport::HashWithIndifferentAccess.new(
      # Dense enough to fill ~2–3 rows on a typical desktop without waiting on scroll
      per_page: 24,
      grid_columns: 3
    )

    TAG_CLOUD = ActiveSupport::HashWithIndifferentAccess.new(
      threshold: 2,
      heatmap: true,
      keypair: true,
      sorting: "frequency"
    )

    FILE_LIST = ActiveSupport::HashWithIndifferentAccess.new(
      hide_presupported_versions: true
    )
  end
end
