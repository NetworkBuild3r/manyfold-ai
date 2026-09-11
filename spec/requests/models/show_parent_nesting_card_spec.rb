# frozen_string_literal: true

require "cgi"
require "rails_helper"

# INIT-025/SPEC-006 — path-parent Merge card is nesting explanation when merge_targets empty (ADR D-4 / D-5).
RSpec.describe "Model show parent nesting card" do
  [:multiuser, :singleuser].each do |mode|
    context "when signed in as moderator in #{mode} mode", mode, :as_moderator do # rubocop:todo RSpec/MultipleMemoizedHelpers
      let(:library) { create(:library) }
      let!(:girl) do
        create(:model, library: library, path: "AnySTL/Girl Sitting on Dinosaur", name: "Girl Sitting on Dinosaur")
      end
      let!(:stormtrooper) do
        create(
          :model,
          library: library,
          path: "AnySTL/Girl Sitting on Dinosaur/Alliance-Stormtrooper_Samurai_NSFW",
          name: "Alliance Stormtrooper"
        )
      end
      let(:unescaped_body) { CGI.unescapeHTML(response.body) }

      describe "GET /models/:id with empty merge_targets" do
        before { get "/models/#{stormtrooper.to_param}" }

        it "does not render merge_models_path to the path parent" do
          expect(response).to have_http_status(:success)
          expect(unescaped_body).not_to include(merge_models_path)
        end

        it "links to the parent model" do
          expect(unescaped_body).to include(model_path(girl))
          expect(unescaped_body).to include(%(aria-label="#{I18n.t("models.show.nesting.parent_link", name: girl.name)}"))
        end

        it "explains nesting without inviting merge into the dump" do
          expect(unescaped_body).to include(I18n.t("models.show.nesting.heading", parents: girl.name))
          expect(unescaped_body).to include(I18n.t("models.show.nesting.explanation"))
          expect(unescaped_body).not_to include(I18n.t("models.show.merge.warning"))
          expect(unescaped_body).not_to include(I18n.t("models.show.merge.with"))
        end
      end

      it "renders Merge when eligibility returns a target" do
        allow(Model::MergeEligibility).to receive(:merge_targets).and_return([girl])
        get "/models/#{stormtrooper.to_param}"
        expect(unescaped_body).to include(merge_models_path(target: girl.public_id, models: [stormtrooper.public_id]))
        expect(unescaped_body).to include(I18n.t("models.show.merge.warning"))
      end
    end
  end
end
