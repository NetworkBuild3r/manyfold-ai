# frozen_string_literal: true

# INIT-027/SPEC-003 — ActorCard render must not raise NoMethodError (LB-1).
require "rails_helper"

RSpec.describe Components::ActorCard, type: :component do
  let(:actor) { create(:actor, :distant, name: "Remote Follow Target") }

  before do
    allow(SiteSettings).to receive(:social_enabled?).and_return(false)
  end

  it "renders the actor name without raising" do
    html = render described_class.new(actor: actor)
    expect(html).to include("Remote Follow Target")
  end

  it "links open to the actor profile_url" do
    html = render described_class.new(actor: actor)
    expect(html).to include(actor.profile_url)
    expect(html).to include("Open")
  end
end
