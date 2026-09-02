# frozen_string_literal: true

require "rails_helper"

# INIT-019/SPEC-007
RSpec.describe "oEmbed redirect" do
  it "rejects a protocol-relative path and does not 303 to //host" do
    get "/oembed", params: {url: "http://x.example//evil.example/x"}
    expect(response).to have_http_status(:bad_request)
    expect(response).not_to be_redirect
  end

  it "redirects a same-origin model URL to the .oembed representation" do
    get "/oembed", params: {url: "http://www.example.com/models/abc123", maxwidth: 256, maxheight: 256}
    expect(response).to redirect_to("http://www.example.com/models/abc123.oembed?maxheight=256&maxwidth=256")
  end
end
