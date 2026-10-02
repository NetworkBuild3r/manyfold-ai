# frozen_string_literal: true

require "rails_helper"

RSpec.describe DuplicateTriage::ThroughputProbe do
  before do
    require Rails.root.join("lib/tasks/duplicate_triage_probe")
  end

  it "reads JSON after a banner whose first exact line is [" do
    path = Rails.root.join("tmp/duplicate_triage_probe_sample.json")
    FileUtils.mkdir_p(path.dirname)
    File.write(path, "Server: banner\nnot json [\n[\n{\"byte_containment\":1}\n]\n")
    rows = described_class.load_evidence_file(path)
    expect(rows).to eq([{"byte_containment" => 1}])
  ensure
    FileUtils.rm_f(path)
  end
end
