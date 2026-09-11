# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-011 — InputRow is abstract; TextInputRow exercises errors_for.
RSpec.describe Components::InputRow, type: :component do
  it "renders ERROR_CLASS from the constant when the attribute has errors" do
    object = Model.new
    object.errors.add(:name, :blank)
    form = ActionView::Helpers::FormBuilder.new(:model, object, view_context, {})
    html = render Components::TextInputRow.new(form: form, attribute: :name, label: "Name")
    expect(html).to include(%(class="#{described_class::ERROR_CLASS}"))
    expect(html).to include("Name")
  end

  it "returns nil from messages_for when the object has no errors" do
    expect(described_class.messages_for(Model.new, :name)).to be_nil
  end
end
