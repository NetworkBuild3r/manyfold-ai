require "rails_helper"

RSpec.describe HealthChecker do
  describe ".run" do
    it "returns [true, []] when all checks pass" do
      ok, reasons = described_class.run(sidekiq_required: false)
      expect(ok).to be true
      expect(reasons).to eq([])
    end

    it "includes database in reasons when DB check fails" do
      allow(described_class).to receive(:check_database).and_return(false)
      allow(described_class).to receive(:check_redis).and_return(true)

      ok, reasons = described_class.run(sidekiq_required: false)
      expect(ok).to be false
      expect(reasons).to include("database")
    end

    it "includes redis in reasons when Redis check fails" do
      allow(described_class).to receive(:check_database).and_return(true)
      allow(described_class).to receive(:check_redis).and_return(false)

      ok, reasons = described_class.run(sidekiq_required: false)
      expect(ok).to be false
      expect(reasons).to include("redis")
    end

    it "includes sidekiq in reasons when Sidekiq required and no workers" do
      allow(described_class).to receive(:check_database).and_return(true)
      allow(described_class).to receive(:check_redis).and_return(true)
      allow(described_class).to receive(:check_sidekiq).and_return(false)

      ok, reasons = described_class.run(sidekiq_required: true)
      expect(ok).to be false
      expect(reasons).to include("sidekiq")
    end

    it "does not check Sidekiq when sidekiq_required is false" do
      expect(described_class).not_to receive(:check_sidekiq)
      described_class.run(sidekiq_required: false)
    end
  end
end
