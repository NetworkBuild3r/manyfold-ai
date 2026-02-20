# Minimal require for `i18n export` (e.g. in CI lint) so we don't need to boot Rails/DB.
# Use: bundle exec i18n export --config=./config/i18n-js.yml --require=./config/i18n_export_require.rb
require "bundler/setup"
require "i18n"

root = File.expand_path("..", __dir__)
I18n.load_path += Dir[File.join(root, "config/locales/**/*.{rb,yml}")]
I18n.backend.load_translations
I18n.default_locale = :en
