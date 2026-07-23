require "rails_helper"
require "zip"
require "base64"

RSpec.describe ArchiveEntryService do
  include ActiveJob::TestHelper

  around do |ex|
    Dir.mktmpdir("archive_entry_spec") do |tmpdir|
      @library_path = tmpdir
      model_dir = File.join(tmpdir, "model_a")
      FileUtils.mkdir_p(model_dir)
      @zip_path = File.join(model_dir, "pack.zip")
      Zip::File.open(@zip_path, create: true) do |zip|
        zip.get_output_stream("readme.txt") { |f| f.write("hello") }
        zip.get_output_stream("parts/widget.stl") { |f| f.write("solid empty\nendsolid empty\n") }
        zip.get_output_stream("pics/shot.png") do |f|
          # minimal 1x1 PNG
          f.write(Base64.decode64("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
        end
        zip.get_output_stream("__MACOSX/._junk") { |f| f.write("x") }
      end
      Library.destroy_all
      @library = create(:library, path: tmpdir)
      @model = create(:model, library: @library, path: "model_a")
      @file = create(:model_file, model: @model, filename: "pack.zip", attachment: nil)
      @file.attach_existing_file!(refresh: false)
      ex.run
    end
  end

  describe "#list!" do
    it "lists files inside the archive and skips ignored paths" do
      entries = described_class.new(@file).list!
      paths = entries.map(&:pathname)
      expect(paths).to include("readme.txt", "parts/widget.stl", "pics/shot.png")
      expect(paths).not_to include("__MACOSX/._junk")
      expect(@file.reload.archive_entries_listed_count).to eq(3)
    end

    it "classifies mesh and image kinds" do
      described_class.new(@file).list!
      expect(@file.archive_entries.find_by(pathname: "parts/widget.stl").kind).to eq("mesh")
      expect(@file.archive_entries.find_by(pathname: "pics/shot.png").kind).to eq("image")
      expect(@file.archive_entries.find_by(pathname: "readme.txt").kind).to eq("other")
    end
  end

  describe "#enqueue_previews!" do
    it "enqueues preview jobs for mesh and image entries" do
      service = described_class.new(@file)
      service.list!
      expect {
        service.enqueue_previews!
      }.to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob).at_least(:twice)
    end

    it "skips mesh previews when images_only" do
      service = described_class.new(@file)
      service.list!
      expect {
        service.enqueue_previews!(images_only: true)
      }.to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob).once
      expect(@file.archive_entries.find_by(pathname: "pics/shot.png").status).to eq("preview_pending")
      expect(@file.archive_entries.find_by(pathname: "parts/widget.stl").status).to eq("listed")
    end
  end

  describe "#extract_to_cache!" do
    it "extracts a single mesh into .manyfold archive_cache" do
      service = described_class.new(@file)
      service.list!
      entry = @file.archive_entries.find_by!(pathname: "parts/widget.stl")
      rel = service.extract_to_cache!(entry)
      expect(rel).to include(".manyfold/archive_cache/")
      expect(File.file?(File.join(@library_path, rel))).to be true
      expect(entry.reload.extracted_path).to eq(rel)
    end
  end
end
