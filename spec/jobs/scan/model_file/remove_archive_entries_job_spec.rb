require "rails_helper"
require "zip"

RSpec.describe Scan::ModelFile::RemoveArchiveEntriesJob do
  let(:library_path) { Dir.mktmpdir("remove_archive_entries_job_spec") }
  let(:model_dir) { File.join(library_path, "model_a") }
  let(:model) do
    Library.destroy_all
    create(:model, library: create(:library, path: library_path), path: "model_a")
  end
  let(:archive) do
    Zip::File.open(File.join(model_dir, "pack.zip"), create: true) do |zip|
      {"readme.txt" => "hello", "pics/shot.png" => "png", "pics/other.png" => "other"}.each do |path, data|
        zip.get_output_stream(path) { |f| f.write(data) }
      end
    end
    file = create(:model_file, model: model, filename: "pack.zip", attachment: nil)
    file.attach_existing_file!(refresh: false)
    ArchiveEntryService.new(file).list!
    file
  end

  before { FileUtils.mkdir_p(model_dir) }

  after { FileUtils.rm_rf(library_path) }

  def entry(pathname)
    archive.archive_entries.find_by!(pathname: pathname)
  end

  def zip_paths
    Zip::File.open(File.join(model_dir, "pack.zip")) { |zip| zip.map(&:name) }
  end

  it "removes dismissed entries from the archive and cleans up their records" do # rubocop:disable RSpec/ExampleLength
    kept = entry("pics/other.png")
    shot = entry("pics/shot.png")
    preview_dir = File.join(model_dir, ".manyfold", "derivatives", "archives", archive.public_id, shot.public_id)
    FileUtils.mkdir_p(preview_dir)
    shot.update!(status: "dismissed")
    old_digest = archive.digest

    described_class.perform_now(archive.id)

    expect(zip_paths).to contain_exactly("readme.txt", "pics/other.png")
    expect(ArchiveEntry.exists?(shot.id)).to be false
    expect(Dir.exist?(preview_dir)).to be false
    expect(kept.reload.public_id).to eq(kept.public_id)
    expect(archive.reload.digest).to eq(Digest::SHA512.file(File.join(model_dir, "pack.zip")).hexdigest)
    expect(archive.digest).not_to eq(old_digest)
  end

  it "removes every dismissed entry in one rewrite" do
    entry("pics/shot.png").update!(status: "dismissed")
    entry("pics/other.png").update!(status: "dismissed")
    allow(Archive::RemoveEntries).to receive(:call).and_call_original

    described_class.perform_now(archive.id)

    expect(Archive::RemoveEntries).to have_received(:call).once
    expect(zip_paths).to eq(["readme.txt"])
  end

  it "keeps unwritable entries dismissed and records why" do
    shot = entry("pics/shot.png")
    shot.update!(status: "dismissed")
    allow(Archive::RemoveEntries).to receive(:call)
      .and_return(Archive::RemoveEntries::Result.new(status: :unwritable, removed: []))

    described_class.perform_now(archive.id)

    expect(shot.reload.status).to eq("dismissed")
    expect(shot.error_message).to eq(described_class::UNWRITABLE_MESSAGE)
  end

  it "does nothing when the archive has no dismissed entries" do
    allow(Archive::RemoveEntries).to receive(:call)

    described_class.perform_now(archive.id)

    expect(Archive::RemoveEntries).not_to have_received(:call)
  end
end
