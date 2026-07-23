# frozen_string_literal: true

require "rails_helper"
require "zip"

RSpec.describe Scan::EnqueueArchiveScansJob do
  include ActiveJob::TestHelper

  around do |ex|
    Dir.mktmpdir("enqueue_archive_scans") do |tmpdir|
      Library.destroy_all
      @library = create(:library, path: tmpdir)
      @model = create(:model, library: @library, path: "pack_model")
      model_dir = File.join(tmpdir, "pack_model")
      FileUtils.mkdir_p(model_dir)
      zip_path = File.join(model_dir, "pack.zip")
      Zip::File.open(zip_path, create: true) do |zip|
        zip.get_output_stream("a.stl") { |f| f.write("solid a\nendsolid a\n") }
      end
      @file = create(:model_file, model: @model, filename: "pack.zip", attachment: nil)
      @file.attach_existing_file!(refresh: false)
      ex.run
    end
  end

  it "enqueues ListArchiveJob for unlisted archives" do
    expect {
      described_class.perform_now(limit: 10, batch_size: 10, stagger: 0, preview_images_only: true)
    }.to have_enqueued_job(Scan::ModelFile::ListArchiveJob)
      .with(@file.id, preview_images_only: true)
  end

  it "skips archives that already have listings unless force" do
    @file.update!(archive_entries_listed_count: 3)
    expect {
      described_class.perform_now(limit: 10, batch_size: 10, stagger: 0)
    }.not_to have_enqueued_job(Scan::ModelFile::ListArchiveJob)
  end
end
