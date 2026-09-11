# frozen_string_literal: true

require "rails_helper"

# INIT-028/SPEC-002 — D-1 resolver matrix; caller supplies user + site_theme.
RSpec.describe ThemeResolver do
  describe ".call" do
    [
      {user_theme: "light", site_theme: "dark", expected: "light", desc: "valid user overlay wins"},
      {user_theme: "dark", site_theme: "light", expected: "dark", desc: "valid user dark overlay"},
      {user_theme: "system", site_theme: "light", expected: "system", desc: "valid user system overlay"},
      {user_theme: nil, site_theme: "dark", expected: "dark", desc: "nil user overlay inherits instance"},
      {user_theme: "", site_theme: "light", expected: "light", desc: "blank user overlay inherits instance"},
      {user_theme: "Darkly", site_theme: "light", expected: "light", desc: "invalid user value falls through"},
      {user_theme: "inherit", site_theme: "dark", expected: "dark", desc: "string inherit is invalid and falls through"},
      {user_theme: nil, site_theme: "not-a-theme", expected: "system", desc: "invalid instance falls through to system"}
    ].each do |row|
      it "#{row[:desc]} → #{row[:expected]}" do
        user = row[:user_theme].nil? && row[:desc].include?("nil user overlay") ? instance_double(User, interface_theme: nil) : instance_double(User, interface_theme: row[:user_theme])
        expect(described_class.call(user: user, site_theme: row[:site_theme])).to eq(row[:expected])
      end
    end

    it "treats a nil user as anonymous (no overlay)" do
      expect(described_class.call(user: nil, site_theme: "dark")).to eq("dark")
    end

    it "uses SiteSettings.validated_theme when site_theme is omitted" do
      allow(SiteSettings).to receive(:validated_theme).and_return("light")
      user = instance_double(User, interface_theme: nil)
      expect(described_class.call(user: user)).to eq("light")
    end

    it "does not execute theme strings as HTML or CSS" do
      user = instance_double(User, interface_theme: "<script>dark</script>")
      expect(described_class.call(user: user, site_theme: "light")).to eq("light")
    end
  end
end
