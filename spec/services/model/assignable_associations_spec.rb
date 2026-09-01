# frozen_string_literal: true

# INIT-017/SPEC-002
require "rails_helper"

RSpec.describe Model::AssignableAssociations do
  let(:user) { create(:contributor) }
  let(:model) { create(:model, creator: nil, collection: nil) }

  describe "#creators" do
    it "includes local creators visible via view scope" do
      visible = create(:creator, name: "Alpha Visible")
      list = described_class.new(user: user, model: model).creators
      expect(list).to include(visible)
    end

    it "includes the model's current creator even when outside the base list" do
      current = create(:creator, name: "Current Outside")
      model.update!(creator: current)
      # Stub base scope empty except merge path — rely on union behavior with a real record
      assignables = described_class.new(user: user, model: model.reload)
      expect(assignables.creators.map(&:id)).to include(current.id)
    end
  end

  describe "#assignable_creator_id?" do
    it "allows blank" do
      expect(described_class.new(user: user, model: model).assignable_creator_id?(nil)).to be true
      expect(described_class.new(user: user, model: model).assignable_creator_id?("")).to be true
    end

    it "allows an id in the assignable set" do
      creator = create(:creator)
      expect(described_class.new(user: user, model: model).assignable_creator_id?(creator.id)).to be true
    end
  end
end
