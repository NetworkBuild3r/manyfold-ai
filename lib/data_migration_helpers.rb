# frozen_string_literal: true

# Shared guard methods for data migrations. Use to avoid loading models against
# an incomplete schema (e.g. on fresh DB or when migrations run in timestamp order).
# Include in data migration classes and use table_ready? / safe_model_each.
module DataMigrationHelpers
  def table_ready?(table, *columns)
    return false unless connection.table_exists?(table)

    columns.all? { |col| connection.column_exists?(table, col) }
  end

  def safe_model_each(klass, &block)
    return unless connection.table_exists?(klass.table_name)

    klass.reset_column_information
    klass.find_each(&block)
  rescue => e
    Rails.logger.warn "[DataMigration] Skipped #{klass}: #{e.message}"
  end
end
