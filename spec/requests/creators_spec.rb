require "rails_helper"

#     creators GET    /creators(.:format)                                                     creators#index
#              POST   /creators(.:format)                                                     creators#create
#  new_creator GET    /creators/new(.:format)                                                 creators#new
# edit_creator GET    /creators/:id/edit(.:format)                                            creators#edit
#      creator GET    /creators/:id(.:format)                                                 creators#show
#              PATCH  /creators/:id(.:format)                                                 creators#update
#              PUT    /creators/:id(.:format)                                                 creators#update
#              DELETE /creators/:id(.:format)                                                 creators#destroy

RSpec.describe "Creators" do
  it_behaves_like "Permittable", Creator

  context "when signed out in multiuser mode", :after_first_run, :multiuser do
    context "with public creator" do
      let!(:creator) { create(:creator, :public) }

      describe "GET /creators" do
        it "includes indexing directive header" do
          allow(SiteSettings).to receive_messages(default_indexable: true, default_ai_indexable: false)
          get "/creators"
          expect(response.headers["X-Robots-Tag"]).to eq "noai noimageai"
        end

        it "includes indexing directive meta tag" do
          allow(SiteSettings).to receive_messages(default_indexable: true, default_ai_indexable: false)
          get "/creators"
          expect(response.body).to include %(<meta name="robots" content="noai noimageai">)
        end
      end

      describe "GET /creators/:id" do
        it "returns http success" do
          get "/creators/#{creator.to_param}"
          expect(response).to have_http_status(:success)
        end

        it "includes indexing directive header" do
          allow(SiteSettings).to receive_messages(default_indexable: true, default_ai_indexable: false)
          get "/creators/#{creator.to_param}"
          expect(response.headers["X-Robots-Tag"]).to eq "noai noimageai"
        end

        it "includes indexing directive meta tag" do
          allow(SiteSettings).to receive_messages(default_indexable: true, default_ai_indexable: false)
          get "/creators/#{creator.to_param}"
          expect(response.body).to include %(<meta name="robots" content="noai noimageai">)
        end
      end
    end

    context "with non-public creator" do
      let(:creator) { create(:creator) }

      describe "GET /creators/:id" do
        it "returns not found" do
          get "/creators/#{creator.to_param}"
          expect(response).to be_not_found
        end
      end
    end
  end

  context "when signed in" do
    before do
      build_list(:creator, 13) do |creator|
        creator.save! # See https://dev.to/hernamvel/the-optimal-way-to-create-a-set-of-records-with-factorybot-createlist-factorybot-buildlist-1j64
        create_list(:link, 1, linkable: creator)
        create_list(:model, 1, creator: creator)
      end
      create(:model, creator: nil)
    end

    describe "GET /creators" do
      it "returns creators with infinite-scroll chrome", :as_member do # rubocop:todo RSpec/MultipleExpectations
        get "/creators"
        expect(response).to have_http_status(:success)
        expect(response.body).to include('data-controller="infinite-scroll"')
        expect(response.body).to include("creator-card-grid")
        expect(response.body).to include("creators-scroll-sentinel-top")
        expect(response.body).to include("creators-scroll-sentinel")
        expect(response.body).not_to match(/pagination/)
      end

      it "keeps unassigned chrome outside the scroll grid", :as_member do
        get "/creators"
        expect(response).to have_http_status(:success)
        expect(response.body).to include("browse-unassigned-chrome")
        # Unassigned must not sit between top sentinel and cards inside the grid.
        grid_start = response.body.index('id="creator-card-grid"')
        unassigned = response.body.index("browse-unassigned-chrome")
        expect(unassigned).to be < grid_start
      end

      it "serves turbo-stream pages for infinite scroll", :as_member do # rubocop:todo RSpec/MultipleExpectations
        get "/creators",
          params: {offset: 0, per_page: 5},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.media_type).to eq("text/vnd.turbo-stream.html")
        expect(response.body).to include("turbo-stream")
        expect(response.body).to include("creators-scroll-sentinel")
        expect(response.body).to include('data-has-more-after="true"')
        expect(response.body).to include('data-offset="0"')
        expect(response.body).not_to include("data-next-url=")
      end

      it "sets has_more_before when offset is past the start", :as_member do
        get "/creators",
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
        get "/creators",
          params: {offset: 5, per_page: 5, window: "before"},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.body).to include('action="after"')
        expect(response.body).to include("creators-scroll-sentinel-top")
      end

      it "marks true end only when offset+returned covers total", :as_member do
        total = Creator.count
        get "/creators",
          params: {offset: [total - 3, 0].max, per_page: 10, window: "after"},
          headers: {
            "Accept" => "text/vnd.turbo-stream.html",
            "X-Infinite-Scroll" => "1"
          }
        expect(response).to have_http_status(:success)
        expect(response.body).to include('data-has-more-after="false"')
      end
    end

    describe "POST /creators" do
      it "creates a new creator and redirects to new item", :as_contributor do
        post "/creators", params: {creator: {name: "newname"}}
        expect(response).to redirect_to("/creators/#{Creator.last.to_param}")
      end

      it "creates a new creator owned by the current user", :as_contributor do # rubocop:disable RSpec/MultipleExpectations
        post "/creators", params: {creator: {name: "newname"}}
        object = Creator.find_by(name: "newname")
        expect(object.grants_permission_to?("own", controller.current_user)).to be true
      end

      it "creates a new creator and redirects to return location if set", :as_contributor do
        model = Model.first
        allow_any_instance_of(CreatorsController).to receive(:session).and_return({return_after_new: edit_model_path(model)}) # rubocop:disable RSpec/AnyInstance
        post "/creators", params: {creator: {name: "newname"}}
        expect(response).to redirect_to("/models/#{model.to_param}/edit?new_creator=#{Creator.find_by(name: "newname").to_param}")
      end

      it "denies member permission", :as_member do
        post "/creators", params: {creator: {name: "newname"}}
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "GET /creators/new" do
      before { get "/creators/new" }

      it "Shows the new creator form", :as_contributor do
        expect(response).to have_http_status(:success)
      end

      it "denies member permission", :as_member do
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "GET /creators/:id/edit" do
      let(:creator) { create(:creator) }

      before { get "/creators/#{creator.to_param}/edit" }

      it "Shows the new creator form", :as_moderator do
        expect(response).to have_http_status(:success)
      end

      it "is denied to non-moderators", :as_contributor do
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "GET /creators/:id", :as_member do
      let(:creator) { create(:creator) }

      it "Redirects to a list of models with that creator" do
        get "/creators/#{creator.to_param}"
        expect(response).to have_http_status(:success)
      end
    end

    describe "PATCH /creators/:id" do
      let(:creator) { create(:creator) }

      before { patch "/creators/#{creator.to_param}", params: {creator: {slug: "newname"}} }

      it "saves details", :as_moderator do
        expect(response).to redirect_to("/creators/newname")
      end

      it "is denied to non-moderators", :as_contributor do
        expect(response).to have_http_status(:forbidden)
      end
    end

    describe "DELETE /creators/:id" do
      let(:creator) { create(:creator) }

      before { delete "/creators/#{creator.to_param}" }

      it "removes creator", :as_moderator do
        expect(response).to redirect_to("/creators")
      end

      it "is denied to non-moderators", :as_contributor do
        expect(response).to have_http_status(:forbidden)
      end
    end
  end
end
