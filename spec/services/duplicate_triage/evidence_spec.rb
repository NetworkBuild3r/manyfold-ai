# frozen_string_literal: true

require "rails_helper"
require "rake"

# Hand-computed (alpha created first ⇒ model_a):
#   files A: aaa@1000, bbb@250
#   files B: aaa@1000, ccc@750, ddd@250
#   shared={aaa}  |A|=2  |B|=3  |A∪B|=4
#   containment = 1/2 = 0.5
#   Jaccard     = 1/4 = 0.25
#   shared_bytes=1000  unique_a=250  unique_b=1000
#   D-5 payload = "aaa#aaa|bbb#aaa|ccc|ddd"
#   SHA256      = e833450e696a044b5ee68bc51a822a97d9d2c4b0fc8a6b5f920ff875a75b90b4
RSpec.describe DuplicateTriage::Evidence, type: :duplicate_triage do
  let(:library) { create(:library) }
  let(:alice) { create(:creator, name: "Alice") }
  let(:bob) { create(:creator, name: "Bob") }
  let!(:alpha) { create(:model, library: library, path: "Pack/Alpha", name: "Alpha", creator: alice) }
  let!(:beta) { create(:model, library: library, path: "Pack/Beta", name: "Beta", creator: bob) }

  before do
    digested_file(alpha, filename: "common.stl", digest: "aaa", size: 1000)
    digested_file(alpha, filename: "extra_a.stl", digest: "bbb", size: 250)
    digested_file(beta, filename: "common.stl", digest: "aaa", size: 1000)
    digested_file(beta, filename: "extra_b.stl", digest: "ccc", size: 750)
    digested_file(beta, filename: "extra_b2.stl", digest: "ddd", size: 250)
  end

  def evidence
    described_class.build(alpha, beta)
  end

  it "matches the hand-computed containment Jaccard and byte totals (AC2)" do
    expect(evidence.containment).to eq(0.5)
    expect(evidence.jaccard).to eq(0.25)
    expect(evidence.shared_bytes).to eq(1000)
    expect(evidence.unique_bytes_a).to eq(250)
    expect(evidence.unique_bytes_b).to eq(1000)
  end

  it "equals the hand-computed D-5 SHA256 (AC2)" do
    expect(alpha.id).to be < beta.id
    expect(evidence.fingerprint).to eq("e833450e696a044b5ee68bc51a822a97d9d2c4b0fc8a6b5f920ff875a75b90b4")
  end

  it "is stable across reruns with no file change (AC3)" do
    expect(described_class.build(alpha, beta).fingerprint).to eq(evidence.fingerprint)
  end

  it "changes when a shared file is added (AC3)" do
    before = evidence.fingerprint
    digested_file(alpha, filename: "new.stl", digest: "eee", size: 10)
    digested_file(beta, filename: "new.stl", digest: "eee", size: 10)
    expect(described_class.build(alpha, beta).fingerprint).to eq(
      "525637af9e1fde30e530a728b16dd0cde0af2fccd89b939f8a2bd99444117271"
    )
    expect(described_class.build(alpha, beta).fingerprint).not_to eq(before)
  end

  it "returns only the evidence fields from to_prompt_h" do
    expect(evidence.to_prompt_h.keys).to eq(described_class::PROMPT_KEYS)
    expect(evidence.to_prompt_h[:creator_a]).to eq("Alice")
    expect(evidence.to_prompt_h[:nested]).to be(false)
  end

  it "prints evidence JSON from the rake task without writing verdicts" do
    Rails.application.load_tasks unless Rake::Task.task_defined?("manyfold:duplicate_triage:evidence")
    task = Rake::Task["manyfold:duplicate_triage:evidence"]
    expect {
      expect { task.execute }.to output(/"fingerprint"/).to_stdout
    }.not_to change(DuplicatePairVerdict, :count)
  end
end
