RSpec.configure do |config|
  config.before(:suite) do
    # Allow remote DATABASE_URL in CI/Docker (e.g. postgresql://manyfold@db:5432/manyfold)
    DatabaseCleaner.allow_remote_database_url = true if ENV["CI"] == "true" || ENV["DOCKER_TEST"] == "1"
    DatabaseCleaner.clean_with(:truncation)
    # Use :deletion in Docker/CI to avoid PG deadlocks when Sidekiq holds a connection (truncation needs exclusive locks).
    DatabaseCleaner.strategy = (ENV["CI"] == "true" || ENV["DOCKER_TEST"] == "1") ? :deletion : :truncation
  end

  config.around do |example|
    DatabaseCleaner.cleaning do
      example.run
    end
  end
end
