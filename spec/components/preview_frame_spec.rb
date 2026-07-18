# frozen_string_literal: true

require "rails_helper"

RSpec.describe Components::PreviewFrame, type: :component do
  let(:model) { create(:model) }
  let!(:file) { create(:model_file, model: model, filename: "cover.jpg") }

  before do
    model.update!(preview_file: file)
    allow(controller).to receive(:policy_scope).and_return(Model.none)
  end

  it "renders an image tag when the preview exists on storage" do
    allow_any_instance_of(ModelFile).to receive(:exists_on_storage?).and_return(true) # rubocop:disable RSpec/AnyInstance
    html = render described_class.new(object: model.reload, lite: true)
    expect(html).to include("<img")
  end

  it "renders the empty placeholder when the preview file is missing on storage" do
    allow_any_instance_of(ModelFile).to receive(:exists_on_storage?).and_return(false) # rubocop:disable RSpec/AnyInstance
    html = render described_class.new(object: model.reload, lite: true)
    expect(html).not_to include("<img")
    expect(html).to include(I18n.t("components.model_card.no_preview"))
  end
end
