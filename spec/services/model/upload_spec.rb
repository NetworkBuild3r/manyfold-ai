# frozen_string_literal: true

require "rails_helper"

RSpec.describe Model::Upload do
  let(:library) { create(:library) }
  let(:owner) { create(:contributor) }

  it "enqueues from API-style string-keyed file hashes" do
    params = {
      "name" => "My New Model",
      "file" => {
        0 => {"id" => "https://example.com/uploads/tus_id", "name" => "test.stl"}
      },
      "license" => "MIT",
      "sensitive" => "1",
      "tag_list" => ["tag1", "tag2"]
    }

    expect {
      described_class.call(library: library, params: params, owner: owner)
    }.to have_enqueued_job(ProcessUploadedFileJob).with(
      library.id,
      [{
        id: "https://example.com/uploads/tus_id",
        storage: "cache",
        metadata: {filename: "test.stl"}
      }],
      hash_including(
        name: "My New Model",
        owner_id: owner.id,
        license: "MIT",
        sensitive: true,
        tag_list: ["tag1", "tag2"]
      )
    ).once
  end
end
