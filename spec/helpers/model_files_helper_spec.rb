require "rails_helper"

RSpec.describe ModelFilesHelper do
  describe "#app_url" do
    let(:file) { create(:model_file, filename: "model.stl") }
    let(:slic3r_family_regex) { "://open\\?file=http%3A%2F%2Ftest.host%2Fmodels%2F#{file.model.to_param}%2Fmodel_files%2Fsigned%2Fey[0-9a-zA-Z-]+%2F#{file.filename}" }

    it "generates orcaslicer links" do
      url = helper.app_url(:orca, file)
      expect(url).to match(/orcaslicer#{slic3r_family_regex}/)
    end

    it "generates bambustudio links" do
      url = helper.app_url(:bambu, file)
      expect(url).to match(/bambustudio#{slic3r_family_regex}/)
    end

    it "generates prusaslicer links" do
      url = helper.app_url(:prusa, file)
      expect(url).to match(/prusaslicer#{slic3r_family_regex}/)
    end

    it "generates superslicer links" do
      # Superslicer uses the prusaslicer URL handler
      url = helper.app_url(:superslicer, file)
      expect(url).to match(/prusaslicer#{slic3r_family_regex}/)
    end

    it "generates cura links" do
      url = helper.app_url(:cura, file)
      expect(url).to match(/cura#{slic3r_family_regex}/)
    end

    it "generates elegoo links" do
      url = helper.app_url(:elegoo, file)
      expect(url).to match(/elegooslicer#{slic3r_family_regex}/)
    end

    it "generates lychee links" do
      url = helper.app_url(:lychee, file)
      expect(url).to match(/lycheeslicer:\/\/open\/http%3A%2F%2Ftest.host%2Fmodels%2F#{file.model.to_param}%2Fmodel_files%2Fsigned%2Fey[0-9a-zA-Z-]+%2F#{file.filename}/)
    end
  end

  describe "#delete_confirmation_for" do
    let(:model) { create(:model) }
    let(:image) { create(:model_file, model: model, filename: "shot.png") }
    let(:base) { I18n.t("model_files.destroy.confirm") }

    def source(filename, writable:)
      archive = create(:model_file, model: model, filename: filename)
      archive.archive_entries.create!(pathname: "pics/shot.png", kind: "image", adopted_model_file: image)
      allow(Archive::RemoveEntries).to receive(:writable?).with(archive).and_return(writable)
      archive
    end

    it "keeps the plain confirmation for files not adopted from an archive" do
      expect(helper.delete_confirmation_for(image)).to eq(base)
    end

    it "names the archives the image will also be removed from" do
      source("Pack.zip", writable: true)

      expect(helper.delete_confirmation_for(image))
        .to eq("#{base} This also removes shot.png from Pack.zip. This cannot be undone.")
    end

    it "says the image stays inside archives that cannot be rewritten" do
      source("Pack.rar", writable: false)

      expect(helper.delete_confirmation_for(image))
        .to eq("#{base} Pack.rar cannot be rewritten, so shot.png will be hidden here but stays inside it.")
    end

    it "checks each archive once per render" do
      source("Pack.zip", writable: true)

      2.times { helper.delete_confirmation_for(image) }

      expect(Archive::RemoveEntries).to have_received(:writable?).once
    end
  end
end
