# frozen_string_literal: true

require "rails_helper"

RSpec.describe Problems::LegacyResolver do
  include Rails.application.routes.url_helpers

  describe ".resolve" do
    def unique_model
      create(:model, public_id: SecureRandom.hex(8))
    end

    it "returns a redirect for :show strategies (e.g. :inside_out)" do
      file = create(:model_file, model: unique_model)
      problem = create(:problem, category: :inside_out, problematic: file)

      result = described_class.resolve(problem)

      expect(result).to eq(redirect: model_model_file_path(file.model, file))
    end

    it "destroys the problem record before destructive side effect when action: :destroy" do
      file = create(:model_file, model: unique_model)
      problem = create(:problem, category: :inside_out, problematic: file)
      problem_id = problem.id

      allow(file).to receive(:delete_from_disk_and_destroy) do
        expect(Problem.unscoped.where(id: problem_id)).not_to exist
      end

      result = described_class.resolve(problem, action: :destroy)

      expect(result).to eq(removed: true)
      expect(Problem.unscoped.where(id: problem_id)).not_to exist
      expect(file).to have_received(:delete_from_disk_and_destroy)
    end
  end
end
