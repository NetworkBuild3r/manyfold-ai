require "rails_helper"

RSpec.describe Archive::EnsurePreview do
  include ActiveJob::TestHelper

  let(:library_path) { Dir.mktmpdir("ensure_preview_spec") }
  let(:model) do
    Library.destroy_all
    create(:model, library: create(:library, path: library_path), path: "model_a", preview_file: nil)
  end
  let(:archive) { create(:model_file, model: model, filename: "pack.zip", attachment: nil) }

  before do
    FileUtils.mkdir_p(File.join(library_path, "model_a"))
    allow(SiteSettings).to receive(:max_file_extract_size).and_return(1_000)
  end

  after { FileUtils.rm_rf(library_path) }

  def entry(pathname, size: 10, status: "listed", kind: "image")
    archive.archive_entries.create!(pathname: pathname, size: size, status: status, kind: kind)
  end

  it "assigns an on-disk image when one exists" do
    File.binwrite(File.join(library_path, "model_a", "photo.png"), "png")
    photo = create(:model_file, model: model, filename: "photo.png", attachment: nil)

    expect(described_class.call(model)).to eq(:assigned)
    expect(model.reload.preview_file).to eq(photo)
  end

  it "queues the best archive image for adoption, preferring preview names" do
    entry("shots/a.png", size: 5)
    cover = entry("shots/cover.png", size: 50)

    expect {
      expect(described_class.call(model)).to eq(:enqueued)
    }.to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob).with(cover.id)
    expect(cover.reload.status).to eq("preview_pending")
  end

  it "skips ineligible entries so they cannot block a usable image" do
    entry("big-cover.png", size: 5_000)
    entry("failed-cover.png", status: "preview_failed")
    entry("gone-cover.png", status: "dismissed")
    entry("huge-cover.png", status: "too_large")
    entry("adopted-cover.png").update!(adopted_model_file: create(:model_file, model: model, filename: "x.png", attachment: nil))
    entry("part.stl", kind: "mesh")
    usable = entry("plain.png")

    expect {
      described_class.call(model)
    }.to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob).with(usable.id)
  end

  it "does nothing when there is no eligible archive image" do
    entry("failed.png", status: "preview_failed")

    expect {
      expect(described_class.call(model)).to be_nil
    }.not_to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob)
  end

  it "logs and returns nil instead of raising" do
    allow(PreviewFilePicker).to receive(:new).and_raise(Errno::EIO)
    allow(Rails.logger).to receive(:warn)

    expect(described_class.call(model)).to be_nil
    expect(Rails.logger).to have_received(:warn).with(/\[EnsurePreview\] model=#{model.id} Errno::EIO/)
  end
end
