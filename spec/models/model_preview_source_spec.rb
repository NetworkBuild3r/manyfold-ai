# frozen_string_literal: true

# INIT-026/SPEC-002
require "rails_helper"
require Rails.root.join("db/migrate/20260910192000_add_preview_archive_entry_and_digest.rb")

RSpec.describe Model, order: :defined do
  let(:model) { create(:model) }
  let(:archive_file) { create(:model_file, model: model, filename: "pack.zip") }
  let(:loose_image) { create(:model_file, model: model, filename: "cover.jpg") }
  let(:entry) do
    ArchiveEntry.create!(
      model_file: archive_file,
      pathname: "pics/shot.png",
      kind: "image",
      status: "preview_ready"
    )
  end

  def other_model_entry
    other = create(:model)
    other_file = create(:model_file, model: other, filename: "other.zip")
    ArchiveEntry.create!(
      model_file: other_file,
      pathname: "pics/foreign.png",
      kind: "image",
      status: "preview_ready"
    )
  end

  describe "ac-1: archive entry belonging to the model" do
    it "allows preview_archive_entry to be an entry of one of its files" do
      expect { model.update!(preview_archive_entry: entry) }.not_to raise_error
      expect(model.reload.preview_archive_entry).to eq(entry)
      expect(model.preview_file).to be_nil
    end

    it "rejects an archive entry that belongs to another model" do
      foreign = other_model_entry
      model.preview_archive_entry = foreign
      expect(model).not_to be_valid
      expect(model.errors[:preview_archive_entry]).to include("must belong to this model")
    end
  end

  describe "ac-2: exclusive preview sources" do
    it "clears preview_archive_entry when a loose preview_file is set" do
      model.update!(preview_archive_entry: entry)
      model.update!(preview_file: loose_image)
      model.reload
      expect(model.preview_file).to eq(loose_image)
      expect(model.preview_archive_entry).to be_nil
    end

    it "clears preview_file when a preview_archive_entry is set" do
      model.update!(preview_file: loose_image)
      model.update!(preview_archive_entry: entry)
      model.reload
      expect(model.preview_archive_entry).to eq(entry)
      expect(model.preview_file).to be_nil
    end

    it "nullifies preview_archive_entry_id when the entry is destroyed" do
      model.update!(preview_archive_entry: entry)
      entry.destroy!
      expect(model.reload.preview_archive_entry_id).to be_nil
    end
  end

  describe "ac-3: nullable archive_entries.digest" do
    it "persists without a digest" do
      expect(entry.digest).to be_nil
      expect(entry).to be_valid
      expect(entry.reload.digest).to be_nil
    end

    it "stores an optional digest when provided" do
      entry.update!(digest: "abc123")
      expect(entry.reload.digest).to eq("abc123")
    end
  end

  describe AddPreviewArchiveEntryAndDigest do
    def reset_preview_source_columns!
      Model.reset_column_information
      ArchiveEntry.reset_column_information
    end

    def migrate_preview_source!(direction)
      ActiveRecord::Migration.suppress_messages do
        AddPreviewArchiveEntryAndDigest.new.migrate(direction)
      end
      reset_preview_source_columns!
    end

    def restore_preview_source_schema!
      return if Model.column_names.include?("preview_archive_entry_id")

      migrate_preview_source!(:up)
    end

    after { restore_preview_source_schema! }

    it "drops preview_archive_entry_id and digest on down" do
      migrate_preview_source!(:down)
      expect(Model.column_names).not_to include("preview_archive_entry_id")
      expect(ArchiveEntry.column_names).not_to include("digest")
    end

    it "re-adds a nullify FK to archive_entries on up" do
      migrate_preview_source!(:down)
      migrate_preview_source!(:up)
      fk = ActiveRecord::Base.connection.foreign_keys(:models).find { |item|
        item.column == "preview_archive_entry_id"
      }
      expect(fk.to_table).to eq("archive_entries")
      expect(fk.on_delete).to eq(:nullify)
    end

    it "indexes models.preview_archive_entry_id" do
      indexed = ActiveRecord::Base.connection.indexes(:models).any? { |idx|
        idx.columns == ["preview_archive_entry_id"]
      }
      expect(indexed).to be true
    end
  end
end
