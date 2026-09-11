# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-006
RSpec.describe Components::FileInputRow, type: :component do
  it "applies TextInputRow::INPUT_CLASS to the file input" do
    form = ActionView::Helpers::FormBuilder.new(:test, nil, view_context, {})
    html = render described_class.new(form: form, attribute: :avatar, label: "Avatar")
    expect(html).to include(%(class="#{Components::TextInputRow::INPUT_CLASS}"))
    expect(html).to include('type="file"')
  end
end
