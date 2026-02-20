# frozen_string_literal: true

require "rails_helper"

RSpec.describe Problems::EmptyModel do
  describe ".detect" do
    it "creates a problem when model has no files" do
      model = create(:model)
      expect(model.model_files).to be_empty

      expect { described_class.detect(model) }.to change(Problem.unscoped, :count).by(1)
      expect(Problem.unscoped.find_by(problematic: model, category: :empty)).to be_present
    end

    it "clears the problem when model has files" do
      model = create(:model)
      create(:model_file, model: model, filename: "part.stl")
      Problem.create_or_clear(model, :empty, true)

      expect { described_class.detect(model) }.to change(Problem.unscoped, :count).by(-1)
      expect(Problem.unscoped.find_by(problematic: model, category: :empty)).to be_nil
    end
  end

  describe "#resolve!" do
    context "with action: :destroy" do
      it "destroys the problem and the model and returns { removed: true }" do
        model = create(:model)
        problem = create(:problem_on_model, category: :empty, problematic: model)
        problem_id = problem.id
        model_id = model.id

        result = described_class.new.resolve!(problem, action: :destroy)

        expect(result).to eq(removed: true)
        expect(Problem.exists?(problem_id)).to be false
        expect(Model.exists?(model_id)).to be false
      end
    end

    context "with action: :ignore" do
      it "marks the problem ignored and returns { ignored: true }" do
        model = create(:model)
        problem = create(:problem_on_model, category: :empty, problematic: model)

        result = described_class.new.resolve!(problem, action: :ignore)

        expect(result).to eq(ignored: true)
        expect(problem.reload.ignored).to be true
      end
    end

    context "with unsupported action" do
      it "raises ArgumentError" do
        problem = create(:problem_on_model, category: :empty)

        expect {
          described_class.new.resolve!(problem, action: :invalid)
        }.to raise_error(ArgumentError, /Unsupported action for EmptyModel/)
      end
    end
  end
end
