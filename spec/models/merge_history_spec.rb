# frozen_string_literal: true

require "rails_helper"

RSpec.describe MergeHistory do
  describe "#source_preview_filename" do
    it "returns preview_filename from source_metadata" do
      target = create(:model, public_id: SecureRandom.hex(8))
      history = described_class.create!(
        target_model: target,
        source_library_id: target.library_id,
        source_path: "parent/child",
        source_name: "Child",
        source_metadata: {"preview_filename" => "preview.png"},
        moved_files: []
      )

      expect(history.source_preview_filename).to eq("preview.png")
    end

    it "returns nil when preview_filename is missing" do
      target = create(:model, public_id: SecureRandom.hex(8))
      history = described_class.create!(
        target_model: target,
        source_library_id: target.library_id,
        source_path: "parent/child",
        source_name: "Child",
        source_metadata: {},
        moved_files: []
      )

      expect(history.source_preview_filename).to be_nil
    end
  end
end
