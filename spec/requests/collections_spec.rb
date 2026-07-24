require "rails_helper"

#      collections GET    /collections(.:format)                                                  collections#index
#                  POST   /collections(.:format)                                                  collections#create
#   new_collection GET    /collections/new(.:format)                                              collections#new
#  edit_collection GET    /collections/:id/edit(.:format)                                         collections#edit
#       collection GET    /collections/:id(.:format)                                              collections#show
#                  PATCH  /collections/:id(.:format)                                              collections#update
#                  PUT    /collections/:id(.:format)                                              collections#update
#                  DELETE /collections/:id(.:format)                                              collections#destroy

RSpec.describe "Collections" do
  it_behaves_like "Permittable", Collection

  context "when signed out in multiuser mode", :after_first_run, :multiuser do
    context "with public collection" do
      let!(:collection) { create(:collection, :public) }

      describe "GET /collections" do
        it "includes indexing directive header" do
          allow(SiteSettings).to receive_messages(default_indexable: true, default_ai_indexable: false)
          get "/collections"
          expect(response.headers["X-Robots-Tag"]).to eq "noai noimageai"
        end

        it "includes indexing directive meta tag" do
          allow(SiteSettings).to receive_messages(default_indexable: true, default_ai_indexable: false)
          get "/collections"
          expect(response.body).to include %(<meta name="robots" content="noai noimageai">)
        end
      end

      describe "GET /collections/:id" do
        it "returns http success" do
          get "/collections/#{collection.to_param}"
          expect(response).to have_http_status(:success)
        end

        it "includes indexing directive header" do
          allow(SiteSettings).to receive_messages(default_indexable: true, default_ai_indexable: false)
          get "/collections/#{collection.to_param}"
          expect(response.headers["X-Robots-Tag"]).to eq "noai noimageai"
        end

        it "includes indexing directive meta tag" do
          allow(SiteSettings).to receive_messages(default_indexable: true, default_ai_indexable: false)
          get "/collections/#{collection.to_param}"
          expect(response.body).to include %(<meta name="robots" content="noai noimageai">)
        end
      end
    end

    context "with non-public collection" do
      let!(:collection) { create(:collection) }

      describe "GET /collections/:id" do
        it "returns not found" do
          get "/collections/#{collection.to_param}"
          expect(response).to be_not_found
        end
      end
    end
  end

  context "when signed in" do
    let(:collection) { create(:collection) }

    before do
      build_list(:collection, 13) do |collection|
        collection.save! # See https://dev.to/hernamvel/the-optimal-way-to-create-a-set-of-records-with-factorybot-createlist-factorybot-buildlist-1j64
        create_list(:link, 1, linkable: collection)
        create_list(:model, 1, collection: collection)
      end
      create(:model, collection: nil)
    end

    describe "GET /collections" do
      it "returns collections with infinite-scroll chrome", :as_member do # rubocop:todo RSpec/MultipleExpectations
        get "/collections"
        expect(response).to have_http_status(:success)
        expect(response.body).to include('data-controller="infinite-scroll"')
        expect(response.body).to include("collection-card-grid")
        expect(response.body).to include("collections-scroll-sentinel-top")
        expect(response.body).to include("collections-scroll-sentinel")
        expect(response.body).not_to match(/pagination/)
      end

      it "keeps unassigned chrome outside the scroll grid", :as_member do
        get "/collections"
        expect(response).to have_http_status(:success)
        expect(response.body).to include("browse-unassigned-chrome")
        grid_start = response.body.index('id="collection-card-grid"')
        unassigned = response.body.index("browse-unassigned-chrome")
        expect(unassigned).to be < grid_start
      end

      it "serves turbo-stream pages for infinite scroll", :as_member do # rubocop:todo RSpec/MultipleExpectations
        get "/collections",
          params: {offset: 0, per_page: 5},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.media_type).to eq("text/vnd.turbo-stream.html")
        expect(response.body).to include("turbo-stream")
        expect(response.body).to include("collections-scroll-sentinel")
        expect(response.body).to include('data-has-more-after="true"')
        expect(response.body).to include('data-offset="0"')
        expect(response.body).not_to include("data-next-url=")
      end

      it "sets has_more_before when offset is past the start", :as_member do
        get "/collections",
          params: {offset: 5, per_page: 5, window: "after"},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.body).to include('data-has-more-before="true"')
        expect(response.body).to include('data-offset="5"')
      end

      it "prepends cards when window=before", :as_member do
        get "/collections",
          params: {offset: 5, per_page: 5, window: "before"},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.body).to include('action="after"')
        expect(response.body).to include("collections-scroll-sentinel-top")
      end

      it "marks true end only when offset+returned covers total", :as_member do
        total = Collection.count
        get "/collections",
          params: {offset: [total - 3, 0].max, per_page: 10, window: "after"},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.body).to include('data-has-more-after="false"')
      end
    end

    describe "POST /collections" do
      it "creates a new collection and redirects to list", :as_contributor do
        post "/collections", params: {collection: {name: "newname"}}
        expect(response).to redirect_to("/collections")
      end

      it "creates a new collection owned by the current user", :as_contributor do # rubocop:disable RSpec/MultipleExpectations
        post "/collections", params: {collection: {name: "newname"}}
        object = Collection.find_by(name: "newname")
        expect(object.grants_permission_to?("own", controller.current_user)).to be true
      end

      it "creates a new collection and redirects to return location if set", :as_contributor do
        model = Model.first
        allow_any_instance_of(CollectionsController).to receive(:session).and_return({return_after_new: edit_model_path(model)}) # rubocop:disable RSpec/AnyInstance
        post "/collections", params: {collection: {name: "newname"}}
        expect(response).to redirect_to("/models/#{model.to_param}/edit?new_collection=#{Collection.find_by(name: "newname").to_param}")
      end

      it "denies member permission", :as_member do
        post "/collections", params: {collection: {name: "newname"}}
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "GET /collections/new" do
      before { get "/collections/new" }

      it "Shows the new collection form", :as_contributor do
        expect(response).to have_http_status(:success)
      end

      it "denies member permission", :as_member do
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "GET /collections/:id/edit" do
      before { get "/collections/#{collection.to_param}/edit" }

      it "Shows the new collection form", :as_moderator do
        expect(response).to have_http_status(:success)
      end

      it "is denied to non-moderators", :as_contributor do
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "GET /collections/:id", :as_member do
      it "Shows that collection" do
        get "/collections/#{collection.to_param}"
        expect(response).to have_http_status(:success)
      end

      # INIT-003/SPEC-003 — show must stream models/page (not 406 UnknownFormat)
      it "serves turbo-stream model windows for infinite scroll" do # rubocop:todo RSpec/MultipleExpectations
        create_list(:model, 6, collection: collection)
        get "/collections/#{collection.to_param}",
          params: {offset: 2, per_page: 2, window: "after"},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.media_type).to eq("text/vnd.turbo-stream.html")
        expect(response.body).to include("turbo-stream")
        expect(response.body).to include("models-scroll-sentinel")
        expect(response.body).to include("model-card")
        expect(response.body).to include('action="replace"')
      end

      it "does not leak another collection's models via stream offset" do
        other = create(:collection)
        create_list(:model, 3, collection: collection)
        create(:model, collection: other, name: "secret-other-collection-model")
        get "/collections/#{collection.to_param}",
          params: {offset: 0, per_page: 10, window: "after"},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.body).not_to include("secret-other-collection-model")
      end
    end

    describe "PATCH /collections/:id" do
      it "saves details", :as_moderator do
        patch "/collections/#{collection.to_param}", params: {collection: {name: "newname"}}
        expect(response).to redirect_to("/collections")
      end
    end

    describe "DELETE /collections/:id" do
      before { delete "/collections/#{collection.to_param}" }

      it "removes collection", :as_moderator do
        expect(response).to redirect_to("/collections")
      end

      it "is denied to non-moderators", :as_contributor do
        expect(response).to have_http_status(:forbidden)
      end
    end
  end
end
