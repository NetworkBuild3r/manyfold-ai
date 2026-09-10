# frozen_string_literal: true

# INIT-026/SPEC-004
# rubocop:disable RSpec/InstanceVariable -- tmpdir around matches archive_entry_service_spec
require "rails_helper"
require "zip"
require "base64"

RSpec.describe Archive::DeleteEntry do
  def png_1x1
    Base64.decode64("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
  end

  around do |ex|
    Dir.mktmpdir("archive_delete_entry_spec") do |tmpdir|
      @library_path = tmpdir
      model_dir = File.join(tmpdir, "model_a")
      FileUtils.mkdir_p(model_dir)
      @zip_path = File.join(model_dir, "pack.zip")
      Zip::File.open(@zip_path, create: true) do |zip|
        zip.get_output_stream("pics/keep.png") { |f| f.write(png_1x1) }
        zip.get_output_stream("pics/junk.png") { |f| f.write(png_1x1) }
      end
      Library.destroy_all
      @library = create(:library, path: tmpdir)
      @model = create(:model, library: @library, path: "model_a")
      @file = create(:model_file, model: @model, filename: "pack.zip", attachment: nil)
      @file.attach_existing_file!(refresh: false)
      ex.run
    end
  end

  def zip_member_names(path)
    names = []
    Zip::File.open(path) do |zip|
      zip.each { |entry| names << entry.name unless entry.directory? }
    end
    names
  end

  def service
    ArchiveEntryService.new(@file)
  end

  def listed_image!(pathname)
    @file.archive_entries.create!(
      pathname: pathname,
      kind: "image",
      status: "preview_ready",
      size: png_1x1.bytesize
    )
  end

  describe "#delete_member!" do
    it "removes the listed image pathname from the zip and keeps other members" do
      keep = listed_image!("pics/keep.png")
      junk = listed_image!("pics/junk.png")

      service.delete_member!(junk)

      expect(zip_member_names(@zip_path)).to contain_exactly("pics/keep.png")
      expect(zip_member_names(@zip_path)).not_to include("pics/junk.png")
      expect(ArchiveEntry.find_by(id: junk.id)).to be_nil
      expect(ArchiveEntry.find_by(id: keep.id)).to eq(keep)
      expect(File.file?(@zip_path)).to be true
    end

    it "removes the derivative preview file and destroys the ArchiveEntry row" do
      junk = listed_image!("pics/junk.png")
      preview_rel = File.join(@model.path, ".manyfold", "derivatives", "archives", @file.public_id, junk.public_id, "preview.png")
      preview_abs = File.join(@library_path, preview_rel)
      FileUtils.mkdir_p(File.dirname(preview_abs))
      File.binwrite(preview_abs, png_1x1)
      junk.update!(preview_path: preview_rel)

      service.delete_member!(junk)

      expect(File.file?(preview_abs)).to be false
      expect(ArchiveEntry.find_by(id: junk.id)).to be_nil
    end

    it "clears preview_archive_entry when that member was the base preview" do
      junk = listed_image!("pics/junk.png")
      @model.update!(preview_archive_entry: junk)

      service.delete_member!(junk)

      expect(@model.reload.preview_archive_entry_id).to be_nil
      expect(@model.preview_file_id).to be_nil
    end

    it "keeps the archive file after deleting the last inner image" do
      listed_image!("pics/keep.png")
      junk = listed_image!("pics/junk.png")
      original = File.binread(@zip_path)

      service.delete_member!(junk)
      remaining = @file.archive_entries.find_by!(pathname: "pics/keep.png")
      service.delete_member!(remaining)

      expect(File.file?(@zip_path)).to be true
      expect(File.size(@zip_path)).to be > 0
      expect(File.binread(@zip_path)).not_to eq(original)
      expect(zip_member_names(@zip_path)).to be_empty
    end

    it "rejects an unsafe member pathname without rewriting the archive" do
      listed_image!("pics/keep.png")
      junk = listed_image!("pics/junk.png")
      junk.update_column(:pathname, "../evil.png") # rubocop:disable Rails/SkipsModelValidations -- fixture for jail
      original = File.binread(@zip_path)

      expect { service.delete_member!(junk) }.to raise_error(ArchiveEntryService::UnsafePath)
      expect(File.binread(@zip_path)).to eq(original)
      expect(ArchiveEntry.find_by(id: junk.id)).to be_present
    end

    it "cannot rewrite a file outside the model archive ModelFile path" do
      junk = listed_image!("pics/junk.png")
      original = File.binread(@zip_path)
      allow(@file).to receive(:path_within_library).and_raise(LibraryPathJail::EscapeError, "path escapes library root")

      expect { service.delete_member!(junk) }.to raise_error(ArchiveEntryService::UnsafePath)
      expect(File.binread(@zip_path)).to eq(original)
      expect(ArchiveEntry.find_by(id: junk.id)).to be_present
    end

    it "fails loud on unsupported rewrite formats and leaves the original intact" do
      seven_path = File.join(@library_path, "model_a", "pack.7z")
      payload = "not-a-real-7z-but-must-stay"
      File.binwrite(seven_path, payload)
      seven = create(:model_file, model: @model, filename: "pack.7z", attachment: nil)
      seven.attach_existing_file!(refresh: false)
      entry = seven.archive_entries.create!(pathname: "pics/junk.png", kind: "image", status: "listed")

      expect { ArchiveEntryService.new(seven).delete_member!(entry) }
        .to raise_error(ArchiveEntryService::UnsupportedFormat)
      expect(File.binread(seven_path)).to eq(payload)
      expect(ArchiveEntry.find_by(id: entry.id)).to be_present
    end

    it "is idempotent when the member is already missing from the zip" do
      ghost = listed_image!("pics/already-gone.png")

      expect { service.delete_member!(ghost) }.not_to raise_error
      expect(ArchiveEntry.find_by(id: ghost.id)).to be_nil
      expect(zip_member_names(@zip_path)).to contain_exactly("pics/keep.png", "pics/junk.png")
    end
  end
end
# rubocop:enable RSpec/InstanceVariable
