require "rails_helper"

RSpec.describe "Activities" do
  context "when logged in as admin", :as_administrator do
    describe "GET /" do
      it "returns http success" do
        allow(ActiveJob::Status).to receive(:all).and_return([])
        get "/activity"
        expect(response).to have_http_status(:success)
      end

      it "sorts jobs when some statuses have no last_activity" do
        older = instance_double(
          ActiveJob::Status::Status,
          last_activity: Time.utc(2026, 9, 1),
          read: {serialized_job: {"job_class" => "ScanJob"}}
        )
        missing = instance_double(
          ActiveJob::Status::Status,
          last_activity: nil,
          read: {serialized_job: {"job_class" => "ScanJob"}}
        )
        allow(older).to receive(:[]).and_return(nil)
        allow(older).to receive(:[]).with(:status).and_return(:completed)
        allow(missing).to receive(:[]).and_return(nil)
        allow(missing).to receive(:[]).with(:status).and_return(:queued)
        allow(ActiveJob::Status).to receive(:all).and_return([older, missing])

        get "/activity"
        expect(response).to have_http_status(:success)
      end
    end
  end

  context "when logged in as non-admin", :as_moderator do
    describe "GET /" do
      it "raises a routing error" do
        get "/activity"
        expect(response).to have_http_status :not_found
      end
    end
  end
end
