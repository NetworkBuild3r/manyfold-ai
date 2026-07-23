# frozen_string_literal: true

require "rails_helper"

RSpec.describe Scan::EnqueueArchiveMeshPreviewRerendersJob do
  include ActiveJob::TestHelper

  around do |ex|
    Dir.mktmpdir("mesh_rerender_spec") do |tmpdir|
      Library.destroy_all
      @library = create(:library, path: tmpdir)
      @model = create(:model, library: @library, path: "m")
      FileUtils.mkdir_p(File.join(tmpdir, "m"))
      @file = create(:model_file, model: @model, filename: "pack.zip")
      ex.run
    end
  end

  it "enqueues preview jobs for mesh entries including previously listed-only" do
    ready = ArchiveEntry.create!(
      model_file: @file,
      pathname: "a.stl",
      kind: "mesh",
      status: "preview_ready",
      size: 100
    )
    listed = ArchiveEntry.create!(
      model_file: @file,
      pathname: "b.stl",
      kind: "mesh",
      status: "listed",
      size: 100
    )
    ArchiveEntry.create!(
      model_file: @file,
      pathname: "c.png",
      kind: "image",
      status: "preview_ready",
      size: 50
    )

    expect {
      described_class.perform_now(limit: 10, batch_size: 10, stagger: 0)
    }.to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob).exactly(2).times

    expect(ready.reload.status).to eq("preview_pending")
    expect(listed.reload.status).to eq("preview_pending")
  end
end
