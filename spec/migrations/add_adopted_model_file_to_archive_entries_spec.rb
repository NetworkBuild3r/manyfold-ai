require "rails_helper"
require Rails.root.join("db/migrate/20261007120000_add_adopted_model_file_to_archive_entries")

# Runs against the PostgreSQL test database (the only database this app supports).
# DatabaseCleaner deletes rows but does not undo DDL, so every example puts the schema back.
RSpec.describe AddAdoptedModelFileToArchiveEntries do
  let(:connection) { ActiveRecord::Base.connection }

  def column_present?
    connection.column_exists?(:archive_entries, :adopted_model_file_id)
  end

  def run_migration(direction)
    ActiveRecord::Migration.suppress_messages { described_class.new.migrate(direction) }
    ArchiveEntry.reset_column_information
  end

  after { run_migration(:up) unless column_present? }

  it "adds a nullable, indexed foreign key to model_files" do
    column = connection.columns(:archive_entries).find { |c| c.name == "adopted_model_file_id" }
    foreign_key = connection.foreign_keys(:archive_entries).find { |fk| fk.column == "adopted_model_file_id" }

    expect(column.null).to be true
    expect(connection.index_exists?(:archive_entries, :adopted_model_file_id)).to be true
    expect(foreign_key.to_table).to eq "model_files"
  end

  it "nullifies the link, rather than failing or cascading, when the adopted file is deleted" do
    foreign_key = connection.foreign_keys(:archive_entries).find { |fk| fk.column == "adopted_model_file_id" }
    expect(foreign_key.on_delete).to eq :nullify
  end

  it "rolls back and re-applies without losing existing archive entries" do
    archive = create(:model_file, filename: "pack.zip")
    entry = archive.archive_entries.create!(pathname: "pics/shot.png", kind: "image")

    run_migration(:down)
    expect(column_present?).to be false
    expect(ArchiveEntry.exists?(entry.id)).to be true

    run_migration(:up)
    expect(column_present?).to be true
    expect(entry.reload.adopted_model_file_id).to be_nil
  end
end
