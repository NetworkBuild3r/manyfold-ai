require "rails_helper"
require "support/mock_directory"

RSpec.describe Scan::Library::CreateModelFromPathJob do
  let(:library) { create(:library) }

  it "creates a single model" do
    expect { described_class.perform_now(library.id, "model") }.to change(Model, :count).from(0).to(1)
  end

  it "creates model in library" do
    described_class.perform_now(library.id, "model")
    expect(library.models.count).to be 1
  end

  it "sets correct path in new model" do
    described_class.perform_now(library.id, "model")
    expect(Model.first.path).to eql "model"
  end

  it "queues model new file scan" do
    described_class.perform_now(library.id, "model")
    expect(Scan::Model::AddNewFilesJob).to have_been_enqueued.with(Model.first.id, hash_including(include_all_subfolders: false)).once
  end

  it "queues model new file scan including subfolders" do
    described_class.perform_now(library.id, "model", include_all_subfolders: true)
    expect(Scan::Model::AddNewFilesJob).to have_been_enqueued.with(Model.first.id, hash_including(include_all_subfolders: true)).once
  end

  it "applies automatic new tag" do
    described_class.perform_now(library.id, "model")
    expect(Model.first.tag_list).to include "!new"
  end

  it "does not apply automatic new tag if there isn't one set" do
    allow(SiteSettings).to receive(:model_tags_auto_tag_new).and_return nil
    described_class.perform_now(library.id, "model")
    expect(Model.first.tag_list).to be_empty
  end

  it "does not enqueue Activity publish jobs during a scan batch" do
    expect {
      described_class.perform_now(library.id, "model", scan_batch_id: "batch-xyz")
    }.not_to have_enqueued_job(Activity::ModelPublishedJob)
  end

  it "passes scan_batch_id into AddNewFilesJob" do
    described_class.perform_now(library.id, "model", scan_batch_id: "batch-xyz")
    expect(Scan::Model::AddNewFilesJob).to have_been_enqueued.with(
      Model.first.id,
      hash_including(scan_batch_id: "batch-xyz")
    ).once
  end
end
