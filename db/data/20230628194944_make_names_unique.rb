# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class MakeNamesUnique < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    attributes = [:name, :slug]
    [Creator, Collection].each do |klass|
      next unless connection.table_exists?(klass.table_name)

      klass.reset_column_information
      attributes.each do |attr|
        next unless connection.column_exists?(klass.table_name, attr)

        klass.all.group_by { |it| it.send(attr)&.downcase }.each_pair do |_n, items|
          next unless items.count > 1

          items.slice(1..-1).each do |c|
            c.name = "#{c.name} #{SecureRandom.hex(4)}"
            c.save!
          end
        end
      end
    end
  rescue StandardError => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
