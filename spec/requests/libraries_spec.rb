require "rails_helper"

#      libraries GET    /libraries(.:format)                                                    libraries#index
#                POST   /libraries(.:format)                                                    libraries#create
#    new_library GET    /libraries/new(.:format)                                                libraries#new
#   edit_library GET    /libraries/:id/edit(.:format)                                           libraries#edit
#        library GET    /libraries/:id(.:format)                                                libraries#show
#                PATCH  /libraries/:id(.:format)                                                libraries#update
#                PUT    /libraries/:id(.:format)                                                libraries#update
#                DELETE /libraries/:id(.:format)                                                libraries#destroy

RSpec.describe "Libraries" do
  # INIT-027/SPEC-012 — libraries#index is nested at GET /settings/libraries
  context "when signed out", :after_first_run, :multiuser do
    it "does not authorize GET /settings/libraries" do
      get "/settings/libraries"
      expect(response).to redirect_to("/users/sign_in")
    end
  end

  context "when signed in" do
    let!(:library) do
      create(:library) do |l|
        create_list(:model, 2, library: l)
      end
    end

    describe "GET /settings/libraries" do
      it "denies permission", :as_member do
        get "/settings/libraries"
        expect(response).to have_http_status(:not_found)
      end

      it "is denied to moderators", :as_moderator do
        get "/settings/libraries"
        expect(response).to have_http_status(:not_found)
      end

      it "is denied to contributors", :as_contributor do
        get "/settings/libraries"
        expect(response).to have_http_status(:not_found)
      end

      it "shows list", :as_administrator do
        get "/settings/libraries"
        expect(response).to have_http_status(:success)
        expect(response.body).to include(library.name)
      end

      it "lists only policy_scope rows", :as_administrator do
        hidden = create(:library, name: "HiddenFromScope")
        allow(LibraryPolicy::Scope).to receive(:new).and_wrap_original do |method, user, scope|
          method.call(user, scope.where(id: library.id))
        end
        get "/settings/libraries"
        expect(response).to have_http_status(:success)
        expect(response.body).to include(library.name)
        expect(response.body).not_to include(hidden.name)
      end
    end

    describe "POST /libraries/" do
      before do
        @library_path = Dir.mktmpdir("library_spec")
        post "/libraries", params: {library: {name: "new", path: @library_path}}
      end

      after { FileUtils.remove_entry(@library_path, true) if @library_path && Dir.exist?(@library_path) }

      it "creates a new library", :as_administrator do
        expect(response).to redirect_to("/libraries/#{Library.last.to_param}")
      end

      it "is denied to non-admins", :as_moderator do
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "GET /libraries/new" do
      before { get "/libraries/new" }

      it "shows the new library form", :as_administrator do
        expect(response).to have_http_status(:success)
      end

      it "is denied to non-admins", :as_moderator do
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "GET /libraries/:id/edit" do
      before { get "/libraries/#{library.to_param}/edit" }

      it "shows the edit library form", :as_administrator do
        expect(response).to have_http_status(:success)
      end

      # INIT-027/SPEC-003 — tag-regex add/remove is cocooned, not jQuery (LB-3).
      it "wires cocooned for tag regex rows without jQuery", :as_administrator do
        expect(response.body).to include('data-controller="cocooned"')
        expect(response.body).to include('data-cocooned-trigger="add"')
        expect(response.body).to include('data-cocooned-trigger="remove"')
        expect(response.body).not_to include("jQuery")
        expect(response.body).not_to include("$('#")
      end

      it "is denied to non-administrators", :as_moderator do
        expect(response).to have_http_status(:forbidden)
      end

      it "keeps save and delete as sibling DoButton forms", :as_administrator do # INIT-027/SPEC-013
        path = "/libraries/#{library.to_param}"
        forms = forms_targeting(path)
        update_form = forms.find { |form| method_overrides(form) == ["patch"] }
        delete_form = forms.find { |form| method_overrides(form) == ["delete"] }
        expect(update_form).to be_present
        expect(delete_form).to be_present
        expect(update_form).not_to eq(delete_form)
        expect(update_form.at('input[type="submit"], button[type="submit"]')).to be_present
        expect(update_form.at("[data-turbo-confirm]")).to be_nil
        expect(delete_form.at("[data-turbo-confirm]")).to be_present
        expect(html5_document.at("a[data-method='delete']")).to be_nil
      end
    end

    describe "GET /libraries/:id" do
      it "redirects to models index with library filter", :as_member do
        get "/libraries/#{library.to_param}"
        expect(response).to redirect_to("/models?library=#{library.public_id}")
      end
    end

    describe "PATCH /libraries/:id" do
      before { patch "/libraries/#{library.to_param}", params: {library: {name: "new"}} }

      it "updates the library", :as_administrator do
        expect(response).to redirect_to("/models")
      end

      it "is denied to non-administrators", :as_moderator do
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "DELETE /libraries/:id" do
      before do
        # Add a model and file to test cascading removal
        model = create(:model, library: library)
        create(:model_file, model: model)
        # Remove library
        delete "/libraries/#{library.to_param}"
      end

      it "removes the library", :as_administrator do
        expect(response).to redirect_to("/settings/libraries")
      end

      it "is denied to non-administrators", :as_moderator do
        expect(response).to have_http_status(:forbidden)
      end
    end
  end

  context "when signed in as administrator with no libraries", :as_administrator do
    it "redirects GET /settings/libraries to new library using the scoped collection" do
      get "/settings/libraries"
      expect(response).to redirect_to("/libraries/new")
    end
  end
end
