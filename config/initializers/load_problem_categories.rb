# frozen_string_literal: true

# Eager load problem category classes so they register with Problems::Registry at boot.
Rails.application.config.to_prepare do
  Rails.root.glob("app/models/problems/*.rb").sort.each do |path|
    next if File.basename(path).match?(/\A(base|registry)\.rb\z/)
    load path
  end
rescue NameError, LoadError
  # Allow boot when models not yet loaded (e.g. db:migrate)
end
