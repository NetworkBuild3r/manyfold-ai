require "rails_helper"

RSpec.describe OrganizeModelJob do
  subject(:job) { described_class.new }

  let(:model) { create(:model) }

  it "organizes the model it is given" do
    allow(Model).to receive(:find).with(model.id).and_return(model)
    allow(model).to receive(:organize!)
    job.perform(model.id)
    expect(model).to have_received(:organize!).once
  end

  it "raises for a model that no longer exists, so the failure is visible and retried" do
    expect { job.perform(0) }.to raise_error(ActiveRecord::RecordNotFound)
  end
end
