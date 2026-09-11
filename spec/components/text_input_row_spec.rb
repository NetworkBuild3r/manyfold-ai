# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-011
RSpec.describe Components::TextInputRow, type: :component do
  it "applies INPUT_CLASS from the constant, not a view literal" do
    form = ActionView::Helpers::FormBuilder.new(:model, Model.new, view_context, {})
    html = render described_class.new(form: form, attribute: :name, label: "Name")
    expect(html).to include(%(class="#{described_class::INPUT_CLASS}"))
  end
end
