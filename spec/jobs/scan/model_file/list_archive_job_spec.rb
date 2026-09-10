require "rails_helper"
require "zip"

RSpec.describe Scan::ModelFile::ListArchiveJob do
  include ActiveJob::TestHelper

  around do |ex|
    Dir.mktmpdir("list_archive_job_spec") do |tmpdir|
      model_dir = File.join(tmpdir, "model_b")
      FileUtils.mkdir_p(model_dir)
      zip_path = File.join(model_dir, "bundle.zip")
      Zip::File.open(zip_path, create: true) do |zip|
        zip.get_output_stream("a.stl") { |f| f.write("solid a\nendsolid a\n") }
      end
      Library.destroy_all
      @library = create(:library, path: tmpdir)
      @model = create(:model, library: @library, path: "model_b")
      @file = create(:model_file, model: @model, filename: "bundle.zip", attachment: nil)
      @file.attach_existing_file!(refresh: false)
      ex.run
    end
  end

  it "lists entries and enqueues previews" do
    expect {
      described_class.perform_now(@file.id)
    }.to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob)
    expect(@file.archive_entries.count).to eq(1)
  end

  it "skips mesh preview jobs when preview_images_only" do
    expect {
      described_class.perform_now(@file.id, preview_images_only: true)
    }.not_to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob)
    expect(@file.archive_entries.count).to eq(1)
    expect(@file.archive_entries.first.status).to eq("listed")
  end

  # INIT-026/SPEC-003
  it "skips re-list when the archive is already listed unless force" do
    @file.update!(archive_entries_listed_count: 4)
    expect {
      described_class.perform_now(@file.id)
    }.not_to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob)
    expect(@file.archive_entries.count).to eq(0)
  end

  it "re-lists an already-listed archive when force is true" do
    @file.update!(archive_entries_listed_count: 4)
    described_class.perform_now(@file.id, force: true)
    expect(@file.reload.archive_entries_listed_count).to eq(1)
    expect(@file.archive_entries.count).to eq(1)
  end
end
