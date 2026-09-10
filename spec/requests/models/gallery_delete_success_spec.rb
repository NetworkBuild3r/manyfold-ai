# frozen_string_literal: true

# Provenance: INIT-026/SPEC-006
require "rails_helper"
require "support/mock_directory"
require "zip"
require "base64"

# rubocop:disable RSpec/InstanceVariable -- tmpdir around matches archive delete_entry_spec
RSpec.describe "Models gallery delete success paths" do
  def png_1x1
    Base64.decode64("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
  end

  describe "DELETE loose image", :as_moderator do
    around do |ex|
      MockDirectory.create(["m/cover.jpg"]) do |path|
        @library_path = path
        ex.run
      end
    end

    it "uses existing destroy so the loose image is gone from disk and gallery" do
      library = create(:library, path: @library_path)
      model = create(:model, library: library, path: "m")
      loose = create(:model_file, model: model, filename: "cover.jpg", attachment: nil)
      loose.attach_existing_file!(refresh: false)
      zip = create(:model_file, model: model, filename: "pack.zip")
      entry = ArchiveEntry.create!(
        model_file: zip,
        pathname: "pics/inner.png",
        kind: "image",
        status: "preview_ready",
        preview_path: "m/.manyfold/derivatives/archives/inner.png"
      )
      disk_path = File.join(@library_path, "m/cover.jpg")
      delete model_model_file_path(model, loose)
      expect(response).to redirect_to(model_path(model))
      expect(ModelFile.find_by(id: loose.id)).to be_nil
      expect(File.exist?(disk_path)).to be false
      get gallery_model_path(model)
      expect(response.body).not_to include("#{loose.to_param}.jpg")
      expect(response.body).to include(preview_model_model_file_archive_entry_path(model, zip, entry))
    end
  end

  describe "DELETE archive image", :as_moderator do
    around do |ex|
      Dir.mktmpdir("gallery_archive_delete") do |tmpdir|
        @library_path = tmpdir
        model_dir = File.join(tmpdir, "model_a")
        FileUtils.mkdir_p(model_dir)
        @zip_path = File.join(model_dir, "pack.zip")
        Zip::File.open(@zip_path, create: true) do |zip|
          zip.get_output_stream("pics/keep.png") { |f| f.write(png_1x1) }
          zip.get_output_stream("pics/junk.png") { |f| f.write(png_1x1) }
        end
        @library = create(:library, path: tmpdir)
        @model = create(:model, library: @library, path: "model_a")
        @file = create(:model_file, model: @model, filename: "pack.zip", attachment: nil)
        @file.attach_existing_file!(refresh: false)
        @loose = create(:model_file, model: @model, filename: "cover.jpg")
        ex.run
      end
    end

    it "removes the archive member from the gallery after confirmed destroy" do
      junk = @file.archive_entries.create!(
        pathname: "pics/junk.png",
        kind: "image",
        status: "preview_ready",
        preview_path: "model_a/.manyfold/derivatives/archives/junk.png"
      )
      preview_url = preview_model_model_file_archive_entry_path(@model, @file, junk)
      get gallery_model_path(@model)
      expect(response.body).to include(preview_url)
      delete model_model_file_archive_entry_path(@model, @file, junk)
      expect(response).to redirect_to(model_model_file_path(@model, @file))
      expect(ArchiveEntry.find_by(id: junk.id)).to be_nil
      get gallery_model_path(@model)
      expect(response.body).not_to include(preview_url)
      expect(response.body).to include("#{@loose.to_param}.jpg")
    end
  end
end
# rubocop:enable RSpec/InstanceVariable
