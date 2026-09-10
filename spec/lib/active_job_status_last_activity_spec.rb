require "rails_helper"

RSpec.describe ActiveJob::Status::Status do
  describe "#last_activity" do
    def status_with(payload)
      described_class.new("job-1").tap do |status|
        allow(status).to receive(:read).and_return(payload)
      end
    end

    it "returns the latest timestamp when enqueued_at is an ISO8601 string" do
      status = status_with(
        serialized_job: {"enqueued_at" => "2026-09-10T12:00:00Z"},
        started_at: DateTime.parse("2026-09-10T13:00:00Z"),
        finished_at: nil
      )

      expect(status.last_activity).to be_a(Time)
      expect(status.last_activity.to_i).to eq Time.utc(2026, 9, 10, 13, 0, 0).to_i
    end

    it "returns nil when no timestamps are present" do
      expect(status_with({}).last_activity).to be_nil
    end
  end
end
