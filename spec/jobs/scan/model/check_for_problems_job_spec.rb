require "rails_helper"
require "support/mock_directory"

RSpec.describe Scan::Model::CheckForProblemsJob do
  context "when checking for missing files" do
    around do |ex|
      MockDirectory.create([
        "model_one/test.stl"
      ]) do |path|
        @library_path = path
        ex.run
      end
    end

    let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable

    it "flags models with no folder as a problem" do
      model = create(:model, library: library, path: "missing")
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).to include("missing")
    end

    it "flags up problems for files that don't exist on disk" do
      model = create(:model, path: "model_one", library: library)
      file = create(:model_file, filename: "missing.stl", model: model)
      File.delete(File.join(library.path, file.path_within_library))
      described_class.perform_now(model.id)
      expect(model.model_files.first.problems.map(&:category)).to include("missing")
    end
  end

  context "when checking for missing image files" do
    it "flags models without images as a problem" do
      model = create(:model)
      create(:model_file, filename: "3d.stl", model: model)
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).to include("no_image")
    end

    it "queues adoption of a ready archive image when no preview is set" do
      MockDirectory.create(["pictured/pack.zip", "pictured/.manyfold/preview.png"]) do |path|
        library = create(:library, path: path)
        model = create(:model, library: library, path: "pictured", preview_file: nil)
        file = create(:model_file, model: model, filename: "pack.zip")
        entry = ArchiveEntry.create!(
          model_file: file,
          pathname: "pics/shot.png",
          kind: "image",
          status: "preview_ready",
          preview_path: "pictured/.manyfold/preview.png",
          size: 8
        )

        expect { described_class.perform_now(model.id) }
          .to have_enqueued_job(Scan::ModelFile::PreviewArchiveEntryJob).with(entry.id)
      end
    end

    it "assigns an on-disk image as preview when none is set" do
      MockDirectory.create(["pictured/photo.png", "pictured/part.stl"]) do |path|
        library = create(:library, path: path)
        model = create(:model, library: library, path: "pictured", preview_file: nil)
        create(:model_file, model: model, filename: "part.stl")
        image = create(:model_file, model: model, filename: "photo.png")

        described_class.perform_now(model.id)

        expect(model.reload.preview_file).to eq(image)
      end
    end

    it "still runs the remaining detectors when preview backfill fails" do
      MockDirectory.create(["broken/part.stl"]) do |path|
        library = create(:library, path: path)
        model = create(:model, library: library, path: "broken", preview_file: nil)
        create(:model_file, model: model, filename: "part.stl")
        allow(PreviewFilePicker).to receive(:new).and_raise(Errno::EIO)
        allow(Problems::NoImage).to receive(:detect).and_call_original
        allow(Problems::NoLicense).to receive(:detect).and_call_original
        allow(Problems::MissingFile).to receive(:detect).and_call_original

        described_class.perform_now(model.id)

        expect(Problems::NoImage).to have_received(:detect)
        expect(Problems::NoLicense).to have_received(:detect)
        expect(Problems::MissingFile).to have_received(:detect)
      end
    end
  end

  context "when checking for missing 3d files" do
    it "flags models without 3d files as a problem" do
      model = create(:model)
      create(:model_file, filename: "image.jpg", model: model)
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).to include("no_3d_model")
    end
  end

  context "when checking for missing license" do
    it "flags models without license as a problem" do
      model = create(:model, license: nil)
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).to include("no_license")
    end

    it "doesn't raise a problem for models with license" do
      model = create(:model, license: "CC-BY-4.0")
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).not_to include("no_license")
    end
  end

  context "when checking for missing creator" do
    it "flags models without creator as a problem" do
      model = create(:model)
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).to include("no_creator")
    end

    it "doesn't raise a problem for models with creator" do
      creator = create(:creator)
      model = create(:model, creator: creator)
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).not_to include("no_creator")
    end
  end

  context "when checking for missing links" do
    it "flags models without link as a problem" do
      model = create(:model, links_attributes: [])
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).to include("no_links")
    end

    it "doesn't raise a problem for models with a link" do
      link = Link.new url: "https://example.com"
      model = create(:model, links: [link])
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).not_to include("no_links")
    end
  end

  context "when checking for missing tags" do
    it "flags models without tags as a problem" do
      model = create(:model, tag_list: [])
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).to include("no_tags")
    end

    it "doesn't raise a problem for models with tags" do
      model = create(:model, tag_list: ["tag"])
      described_class.perform_now(model.id)
      expect(model.problems.map(&:category)).not_to include("no_tags")
    end
  end

  it "raises exception if model ID is not found" do
    expect { described_class.perform_now(nil) }.to raise_error(ActiveRecord::RecordNotFound)
  end
end
