require "rails_helper"

#  user_settings GET    /users/:user_id/settings(.:format)                                      settings#show
#                PATCH  /users/:user_id/settings(.:format)                                      settings#update
#                PUT    /users/:user_id/settings(.:format)                                      settings#update

RSpec.describe "Settings" do
  context "when signed out" do
    describe "GET /settings" do
      it "returns access denied" do
        get "/settings"
        expect(response).to redirect_to("/users/sign_in")
      end
    end
  end

  context "when signed in", :as_contributor do
    describe "GET /settings" do
      it "returns not found" do
        get "/settings"
        expect(response).to have_http_status(:not_found)
      end
    end
  end

  context "when signed in", :as_administrator do
    describe "GET /settings" do
      it "returns http success" do
        get "/settings"
        expect(response).to have_http_status(:success)
      end

      # INIT-027/SPEC-005
      it "emits data-accent from validated_accent_color on the application layout" do
        SiteSettings.accent_color = "purple"
        get "/settings"
        expect(response).to have_http_status(:success)
        expect(response.body).to include('data-accent="purple"')
      end

      it "keeps the accent help text that buttons and links follow the picker" do
        get "/settings/appearance"
        expect(response).to have_http_status(:success)
        expect(response.body).to include(I18n.t("settings.appearance.accent.help"))
        expect(I18n.t("settings.appearance.accent.help")).to match(/buttons and links/i)
      end

      # INIT-028/SPEC-003 — D-7 / REQ-007: instance default, not the only control.
      it "describes Appearance theme as the instance default" do
        get "/settings/appearance"
        help = I18n.t("settings.appearance.theme.help_html")
        expect(response.body).to include("Default for visitors and accounts that inherit")
        expect(help).to include("Default for visitors and accounts that inherit")
        expect(help).not_to include("Affects all accounts")
      end
    end

    describe "PATCH /settings" do
      it "redirects back to settings on success" do
        patch "/settings"
        expect(response).to redirect_to("/settings")
      end

      context "with folder settings params" do
        let(:params) {
          {
            folders: {
              model_path_template: "test/{tags}/{modelName}{modelId}",
              parse_metadata_from_path: "1",
              safe_folder_names: "0"
            }
          }
        }

        before do
          SiteSettings.model_path_template = "before"
          SiteSettings.parse_metadata_from_path = false
          SiteSettings.safe_folder_names = true
          patch "/settings", params: params
        end

        it "saves path template" do
          expect(SiteSettings.model_path_template).to eq "test/{tags}/{modelName}{modelId}"
        end

        it "saves parsing setting" do
          expect(SiteSettings.parse_metadata_from_path).to be true
        end

        it "saves safe folder name setting" do
          expect(SiteSettings.safe_folder_names).to be false
        end
      end

      context "with file settings params" do
        let(:params) {
          {
            files: {
              model_ignored_files: "/.*\\.lys/\n/.*\\.lyt/"
            }
          }
        }

        before do
          patch "/settings", params: params
        end

        it "saves file ignore regexes" do
          expect(SiteSettings.model_ignored_files).to contain_exactly(/.*\.lys/, /.*\.lyt/)
        end
      end

      # INIT-028/SPEC-003 — admin Appearance still writes SiteSettings.theme.
      context "with appearance theme params" do
        it "persists a listed theme" do
          SiteSettings.theme = "light"
          patch "/settings", params: {appearance: {theme: "dark"}}
          expect(SiteSettings.theme).to eq "dark"
        end
      end

      # INIT-027/SPEC-005
      context "with appearance accent params" do
        it "persists a listed accent_color" do
          patch "/settings", params: {appearance: {accent_color: "green"}}
          expect(SiteSettings.accent_color).to eq "green"
        end

        it "rejects an unknown accent_color" do
          SiteSettings.accent_color = "indigo"
          patch "/settings", params: {appearance: {accent_color: "chartreuse"}}
          expect(SiteSettings.accent_color).to eq "indigo"
        end
      end
    end
  end
end
