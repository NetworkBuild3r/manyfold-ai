# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class GeneratePublicIDsForModels < ActiveRecord::Migration[7.1]
  include DataMigrationHelpers

  ALPHABET = "bcdfghjklmnpqrstvwxz0123456789"

  def up
    [Model, ModelFile, Creator, Collection, Library].each do |model|
      next unless connection.table_exists?(model.table_name) && connection.column_exists?(model.table_name, :public_id)

      model.reset_column_information
      model.unscoped.where(public_id: nil).find_each do |obj|
        obj.send :generate_public_id
        obj.update_column :public_id, obj.public_id # rubocop:disable Rails/SkipsModelValidations
      end
    end
    backfill_problem_public_ids
  rescue StandardError => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
  end

  private

  def backfill_problem_public_ids
    return unless connection.table_exists?(:problems)
    return unless connection.column_exists?(:problems, :public_id)

    conn = connection
    existing = conn.select_values("SELECT public_id FROM problems WHERE public_id IS NOT NULL").to_set
    conn.execute("SELECT id FROM problems WHERE public_id IS NULL").each do |row|
      id = row["id"]
      public_id = generate_unique_nanoid(existing, conn)
      conn.execute("UPDATE problems SET public_id = #{conn.quote(public_id)} WHERE id = #{conn.quote(id)}")
    end
  end

  def generate_unique_nanoid(existing_set, conn)
    loop do
      id = Nanoid.generate(size: 12, alphabet: ALPHABET)
      next if existing_set.include?(id)
      next if conn.select_value("SELECT 1 FROM problems WHERE public_id = #{conn.quote(id)} LIMIT 1").present?
      existing_set << id
      return id
    end
  end
end
