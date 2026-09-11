# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-006
RSpec.describe Components::BaseButton, type: :component do
  describe Components::DoButton do
    it "renders a form with primary variant classes" do
      html = render described_class.new(
        label: "Save",
        href: "/save",
        variant: "primary"
      )
      expect(html).to include("Save")
      expect(html).to include("bg-primary-600")
      expect(html).to include("action=")
    end

    it "renders secondary variant when specified" do
      html = render described_class.new(
        label: "Cancel",
        href: "/cancel",
        variant: "secondary"
      )
      expect(html).to include("border")
      expect(html).to include("rounded-lg")
    end

    it "keeps named variant class strings stable" do
      Components::BaseButton::VARIANT_CLASSES.each_key do |name|
        next if name == "toolbar"

        html = render described_class.new(label: name, href: "/x", variant: name)
        expect(html).to include(Components::BaseButton::VARIANT_CLASSES.fetch(name).split(" ").first)
      end
    end

    # INIT-027/SPEC-011 — variants must come from VARIANT_CLASSES, not view literals.
    it "emits the full VARIANT_CLASSES constant for primary" do
      html = render described_class.new(label: "Save", href: "/save", variant: "primary")
      expect(html).to include(Components::BaseButton::VARIANT_CLASSES.fetch("primary"))
      expect(html).to include(Components::BaseButton::BASE_CLASSES)
    end

    it "sets turbo_confirm and confirm when confirm: is passed" do
      html = render described_class.new(
        label: "Delete library",
        href: "/libraries/1",
        variant: "danger",
        method: :delete,
        confirm: "Delete this library?"
      )
      expect(html).to include('data-turbo-confirm="Delete this library?"')
      expect(html).to include('data-confirm="Delete this library?"')
    end

    it "omits confirm data attributes when confirm is blank" do
      html = render described_class.new(
        label: "Save",
        href: "/save",
        variant: "primary"
      )
      expect(html).not_to include("data-turbo-confirm")
      expect(html).not_to include("data-confirm")
    end
  end

  describe Components::GoButton do
    it "renders an anchor with outline-secondary classes" do
      html = render described_class.new(
        label: "Edit",
        href: "/edit",
        variant: "outline-secondary"
      )
      expect(html).to include("<a")
      expect(html).to include("border-secondary-300")
    end

    # INIT-027/SPEC-011
    it "emits VARIANT_CLASSES for outline-secondary, not a local literal" do
      html = render described_class.new(label: "Edit", href: "/edit", variant: "outline-secondary")
      expect(html).to include(Components::BaseButton::VARIANT_CLASSES.fetch("outline-secondary"))
    end

    it "sets turbo_confirm on GET navigation when confirm: is passed" do
      html = render described_class.new(
        label: "Continue",
        href: "/next",
        variant: "primary",
        confirm: "Leave this filter?"
      )
      expect(html).to include('data-turbo-confirm="Leave this filter?"')
      expect(html).to include('data-confirm="Leave this filter?"')
    end
  end

  it "defines toolbar as BASE_CLASSES plus secondary variant" do
    expect(described_class::VARIANT_CLASSES.fetch("toolbar")).to eq(
      [described_class::BASE_CLASSES, described_class::VARIANT_CLASSES.fetch("secondary")].join(" ")
    )
  end
end
