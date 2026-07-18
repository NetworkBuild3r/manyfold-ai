require "rails_helper"

RSpec.describe Search::FilterService do
  context "with a range of models" do
    let(:contributor) { create(:contributor) }
    let(:creator) { create(:creator, name: "Dr Seuss") }
    let(:collection) { create(:collection, name: "Chiroptera") }

    before do
      create(:model, name: "cat in the hat", tag_list: ["dog", "log", "frog", "cat"], creator: creator, notes: "lorem ipsum", caption: nil)
      create(:model, name: "hat on the cat", tag_list: [], creator: creator, notes: nil, caption: "dolor sit amet")
      create(:model, name: "bat on a mat", tag_list: ["log"], collection: collection, notes: nil, caption: nil, links_attributes: [{url: "https://thingiverse.com/thing:1234"}])
      create(:model, name: "bat on a hat", tag_list: ["frog"], collection: collection, notes: nil, caption: nil, owner: contributor)
    end

    it "returns all models with no filters" do
      filter = described_class.new(ActionController::Parameters.new)
      expect(filter.models(Model).count).to eq 4
    end

    it "filters on a simple search query" do
      service = described_class.new(ActionController::Parameters.new(q: "cat"))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("cat in the hat", "hat on the cat")
    end

    it "filters by collection" do
      service = described_class.new(ActionController::Parameters.new(collection: collection.to_param))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("bat on a mat", "bat on a hat")
    end

    it "filters by missing collection" do
      service = described_class.new(ActionController::Parameters.new(collection: ""))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("cat in the hat", "hat on the cat")
    end

    it "filters by creator" do
      service = described_class.new(ActionController::Parameters.new(creator: creator.to_param))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("cat in the hat", "hat on the cat")
    end

    it "filters by missing creator" do
      service = described_class.new(ActionController::Parameters.new(creator: ""))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("bat on a mat", "bat on a hat")
    end

    it "filters by single tag" do
      service = described_class.new(ActionController::Parameters.new(tag: ["log"]))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("cat in the hat", "bat on a mat")
    end

    it "filters by no tags" do
      service = described_class.new(ActionController::Parameters.new(tag: [""]))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("hat on the cat")
    end

    it "filters by multiple tags" do
      service = described_class.new(ActionController::Parameters.new(tag: ["log", "frog"]))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("cat in the hat")
    end

    it "filters by missing tag" do
      service = described_class.new(ActionController::Parameters.new(missingtag: "log"))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("hat on the cat", "bat on a hat")
    end

    it "filters by library" do
      service = described_class.new(ActionController::Parameters.new(library: Library.last.to_param))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("bat on a hat")
    end

    it "filters by link" do
      service = described_class.new(ActionController::Parameters.new(link: "thingiverse.com"))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("bat on a mat")
    end

    it "filters by owner" do
      service = described_class.new(ActionController::Parameters.new(owner: contributor.to_param))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("bat on a hat")
    end

    it "filters to models whose preview_file is an image" do
      with_image = Model.find_by!(name: "cat in the hat")
      image = create(:model_file, model: with_image, filename: "preview.jpg")
      with_image.update!(preview_file: image)

      # Image file exists but preview_file unset — excluded (card would show empty)
      orphan = Model.find_by!(name: "hat on the cat")
      create(:model_file, model: orphan, filename: "cover.png")

      # Mesh locked as preview despite an image file — excluded
      mesh_preview = Model.find_by!(name: "bat on a mat")
      stl = create(:model_file, model: mesh_preview, filename: "part.stl")
      create(:model_file, model: mesh_preview, filename: "photo.jpg")
      mesh_preview.update!(preview_file: stl)

      service = described_class.new(ActionController::Parameters.new(has_image: "1"))
      expect(service.models(Model.all).pluck(:name)).to contain_exactly("cat in the hat")
    end

    it "ignores has_image when not truthy" do
      service = described_class.new(ActionController::Parameters.new(has_image: "0"))
      expect(service.models(Model.all).count).to eq 4
    end

    it "treats library/creator/collection 'all' as no filter" do
      service = described_class.new(ActionController::Parameters.new(
        library: "all",
        creator: "all",
        collection: "all"
      ))
      expect(service.any?).to be false
      expect(service.models(Model.all).count).to eq 4
    end
  end
end
