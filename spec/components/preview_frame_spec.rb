# frozen_string_literal: true

require "rails_helper"

RSpec.describe Components::PreviewFrame, type: :component do
  let(:model) { create(:model) }
  let!(:file) { create(:model_file, model: model, filename: "cover.jpg") }

  before do
    model.update!(preview_file: file)
    allow(controller).to receive(:policy_scope).and_return(Model.none)
  end

  it "renders an image tag on lite cards without checking NFS" do
    expect_any_instance_of(ModelFile).not_to receive(:exists_on_storage?) # rubocop:disable RSpec/AnyInstance
    html = render described_class.new(object: model.reload, lite: true)
    expect(html).to include("<img")
    expect(html).to include('width="480"')
    expect(html).to include('height="360"')
    expect(html).to include("absolute inset-0")
  end

  it "renders the empty placeholder when a non-lite preview is missing on storage" do
    allow_any_instance_of(ModelFile).to receive(:exists_on_storage?).and_return(false) # rubocop:disable RSpec/AnyInstance
    html = render described_class.new(object: model.reload, lite: false)
    expect(html).not_to include("<img")
    expect(html).to include(I18n.t("components.model_card.no_preview"))
  end
end
