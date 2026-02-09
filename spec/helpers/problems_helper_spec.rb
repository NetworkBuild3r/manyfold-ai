require "rails_helper"

RSpec.describe ProblemsHelper, :as_member do
  include Devise::Test::ControllerHelpers

  let(:model) { create(:model) }

  it "converts a problem to a severity level" do
    expect(helper.problem_severity(
      build(:problem_on_model, category: :duplicate, problematic: model)
    )).to eq :warning
  end

  it "works out the maximum severity from a set of problems (warning)" do
    Problem.create_or_clear(model, :duplicate, true)
    Problem.create_or_clear(model, :inefficient, true)
    expect(helper.max_problem_severity(Problem.all)).to eq :warning
  end

  it "works out the maximum severity from a set of problems (danger)" do
    Problem.create_or_clear(model, :missing, true)
    Problem.create_or_clear(model, :duplicate, true)
    Problem.create_or_clear(model, :inefficient, true)
    expect(helper.max_problem_severity(Problem.all)).to eq :danger
  end
end
