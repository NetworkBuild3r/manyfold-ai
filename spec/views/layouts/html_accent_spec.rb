# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-005
RSpec.describe "html data-accent layouts" do
  %w[application.html.erb embed.html.erb].each do |layout|
    it "#{layout} binds data-accent to SiteSettings.validated_accent_color" do
      source = Rails.root.join("app/views/layouts", layout).read
      expect(source).to include('data-accent="<%= SiteSettings.validated_accent_color %>"')
    end
  end
end
