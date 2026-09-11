# frozen_string_literal: true

# INIT-027/SPEC-003 — unassigned chrome uses semantic border-warning (LB-4).
require "rails_helper"

RSpec.describe "unassigned browse cards", type: :view do
  before { assign(:unassigned_count, 2) }

  it "uses border-warning on creators unassigned partial" do
    render partial: "creators/unassigned"
    expect(rendered).to include("border-warning")
    expect(rendered).not_to match(/border-warning-\d/)
  end

  it "uses border-warning on collections unassigned partial" do
    render partial: "collections/unassigned"
    expect(rendered).to include("border-warning")
    expect(rendered).not_to match(/border-warning-\d/)
  end

  it "keeps unassigned chrome in the shared partial" do # INIT-027/SPEC-009
    render partial: "application/browse_unassigned", locals: {
      name: "Unassigned",
      caption: "All the models without a known creator.",
      models_params: {creator: ""},
      icon: "people"
    }
    expect(rendered).to include("border-warning")
    expect(rendered).to include("browse-unassigned-card")
  end
end
