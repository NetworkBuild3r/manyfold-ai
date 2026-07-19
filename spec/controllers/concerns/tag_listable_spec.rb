# frozen_string_literal: true

require "rails_helper"

RSpec.describe TagListable, type: :controller do
  controller(ApplicationController) do
    include TagListable
    include Pundit::Authorization

    def index
      head :ok
    end
  end

  before do
    allow(controller).to receive(:policy_scope) { |scope| scope }
    allow(controller).to receive(:helpers).and_return(
      instance_double(
        ApplicationController.helpers.class,
        tag_cloud_settings: {"threshold" => 1, "sorting" => "frequency", "keypair" => false}
      )
    )
  end

  describe "#generate_tag_list" do
    it "does not load every model into memory for a Relation" do
      create(:model, tag_list: ["alpha"])
      create(:model, tag_list: ["beta"])
      scope = Model.all

      expect(scope).not_to receive(:map)
      expect(scope).not_to receive(:to_a)
      expect(scope).not_to receive(:load)

      tags, unrelated = controller.send(:generate_tag_list, scope)
      expect(unrelated).to eq 0
      expect(tags.pluck(:name)).to include("alpha", "beta")
    end

    it "still accepts an Array of models" do
      model = create(:model, tag_list: ["gamma"])
      tags, _ = controller.send(:generate_tag_list, [model])
      expect(tags.pluck(:name)).to include("gamma")
    end
  end
end
