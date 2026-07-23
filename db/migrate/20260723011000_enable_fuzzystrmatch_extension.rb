# frozen_string_literal: true

# Follow-up: short-token typo matching (rouge→rogue) needs levenshtein from
# fuzzystrmatch. The prior pg_trgm migration may already have run in prod.
class EnableFuzzystrmatchExtension < ActiveRecord::Migration[8.0]
  def up
    enable_extension "fuzzystrmatch" unless extension_enabled?("fuzzystrmatch")
  end

  def down
    # Leave installed — search (and other tooling) may depend on it.
  end
end
