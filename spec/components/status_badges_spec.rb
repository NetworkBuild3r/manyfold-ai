# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-011
RSpec.describe Components::StatusBadges, type: :component do
  let(:model) { build_stubbed(:model) }

  it "wraps output in WRAPPER_CLASS from the constant" do
    allow(controller).to receive(:policy).and_return(instance_double(ProblemPolicy, show?: false))
    html = render described_class.new(model: model)
    expect(html).to include(%(class="#{described_class::WRAPPER_CLASS}"))
  end

  it "uses NEW_BADGE_CLASS when the model is tagged new" do
    allow(controller).to receive(:policy).and_return(instance_double(ProblemPolicy, show?: false))
    allow(model).to receive(:new?).and_return(true)
    html = render described_class.new(model: model)
    expect(html).to include(described_class::NEW_BADGE_CLASS)
  end

  it "passes the given model to problems_including_files (LB-2)" do
    component = described_class.new(model: model)
    relation = double("problem_scope") # rubocop:todo RSpec/VerifiedDoubles
    allow(relation).to receive(:visible).and_return([])
    allow(controller).to receive(:policy).and_return(instance_double(ProblemPolicy, show?: true))
    allow(component).to receive(:problems_including_files).with(model).and_return(relation)
    allow(component).to receive_messages(problem_settings: {}, problem_icon_tag: nil)

    render component

    expect(component).to have_received(:problems_including_files).with(model)
  end
end
