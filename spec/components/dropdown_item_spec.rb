# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-006
RSpec.describe Components::DropdownItem, type: :component do
  it "renders a GET item as a link without method: on the anchor" do
    html = render described_class.new(label: "Edit model", path: "/models/1/edit")
    doc = Nokogiri::HTML.fragment(html)
    anchor = doc.at("a")
    expect(anchor).to be_present
    expect(anchor["href"]).to include("/models/1/edit")
    expect(anchor["data-method"]).to be_nil
    expect(doc.at("form")).to be_nil
  end

  it "renders a mutating item as button_to, not link_to method:" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
    html = render described_class.new(
      label: "Delete model",
      path: "/models/1",
      method: :delete,
      confirm: "Delete this model?"
    )
    doc = Nokogiri::HTML.fragment(html)
    expect(doc.at("form")).to be_present
    expect(doc.at("form")["action"]).to include("/models/1")
    expect(html).to include('name="_method"')
    expect(html).to include('value="delete"')
    expect(doc.at("a")).to be_nil
    expect(html).not_to include("data-method")
  end

  it "uses turbo_method and turbo_confirm kwargs for mutating items" do
    html = render described_class.new(
      label: "Delete file",
      path: "/files/1",
      turbo_method: :delete,
      turbo_confirm: "Delete this file?"
    )
    expect(html).to include("<form")
    expect(html).to include('data-turbo-confirm="Delete this file?"')
    expect(html).to include('data-confirm="Delete this file?"')
  end

  # INIT-027/SPEC-011 — class channel is ITEM_CLASS / ACTIVE_ITEM_CLASS.
  it "uses ITEM_CLASS from the constant, not an inline literal" do
    html = render described_class.new(label: "Edit model", path: "/models/1/edit")
    expect(html).to include(described_class::ITEM_CLASS)
  end

  it "appends ACTIVE_ITEM_CLASS when active" do
    html = render described_class.new(label: "Here", path: "/here", active: true)
    expect(html).to include(described_class::ITEM_CLASS)
    expect(html).to include(described_class::ACTIVE_ITEM_CLASS.strip)
  end

  it "does not put method: on GET anchors when confirm is set" do
    html = render described_class.new(
      label: "Open",
      path: "/open",
      confirm: "Leave this page?"
    )
    doc = Nokogiri::HTML.fragment(html)
    expect(doc.at("a")["data-method"]).to be_nil
    expect(html).to include('data-turbo-confirm="Leave this page?"')
  end
end
