# frozen_string_literal: true

require "rails_helper"

RSpec.describe Model, "Followable scan batch gating" do
  before { create(:admin) }

  it "does not post Create activity during a scan batch even if federation is enabled" do
    allow(SiteSettings).to receive(:federation_enabled?).and_return(true)
    expect {
      Current.set(scan_batch_id: "batch-1") { create(:model) }
    }.not_to change { Federails::Activity.where(action: "Create").count }
  end

  it "does not create a federails actor when federation is disabled" do
    allow(SiteSettings).to receive(:federation_enabled?).and_return(false)
    model = create(:model)
    expect(model.federails_actor).to be_nil
    expect(Federails::Actor.where(entity: model).count).to eq 0
  end
end
