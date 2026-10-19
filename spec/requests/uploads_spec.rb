require "rails_helper"

# Uploads go through the tus server mounted at /upload, inside a route constraint that only lets
# signed-in contributors reach it. Visitors who are not signed in are sent to the sign-in page;
# signed-in users without the contributor role get a routing 404, as if it were not there.
RSpec.describe "Uploads" do
  let(:tus_headers) { {"Tus-Resumable" => "1.0.0", "Upload-Length" => "10"} }

  context "when signed out" do
    describe "POST /upload" do
      it "redirects to sign in" do
        post "/upload", headers: tus_headers
        expect(response).to redirect_to(new_user_session_path)
      end
    end
  end

  context "when signed in" do
    describe "POST /upload" do
      it "is denied to non-contributors", :as_member do
        post "/upload", headers: tus_headers
        expect(response).to have_http_status :not_found
      end

      it "starts an upload for contributors", :as_contributor do
        post "/upload", headers: tus_headers
        expect(response).to have_http_status :created
        expect(response.headers["Location"]).to match(%r{/upload/\w+})
      end
    end
  end
end
