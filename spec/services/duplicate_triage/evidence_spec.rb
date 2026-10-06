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
    expect(evidence.to_prompt_h[:total_bytes_a]).to eq(1250)
    expect(evidence.to_prompt_h[:total_bytes_b]).to eq(2000)
    expect(evidence.to_prompt_h[:byte_containment]).to eq(0.8)
  end

  it "prints evidence JSON from the rake task without writing verdicts" do
    Rails.application.load_tasks unless Rake::Task.task_defined?("manyfold:duplicate_triage:evidence")
    task = Rake::Task["manyfold:duplicate_triage:evidence"]
    expect {
      expect { task.execute }.to output(/"byte_containment"[\s\S]*"fingerprint"/).to_stdout
    }.not_to change(DuplicatePairVerdict, :count)
  end
end

# Hand-computed (AC6 / ADR Addendum A-1):
#   shared image 1024 bytes; totals 100_000_000 and 200_000_000
#   byte_containment = 1024 / 100_000_000 = 0.00001024
RSpec.describe DuplicateTriage::Evidence, "byte-weighted overlap (AC6)", type: :duplicate_triage do
  let(:library) { create(:library) }

  def promo_models(bytes_a, bytes_b)
    left = create(:model, library: library, path: "Promo/Left")
    right = create(:model, library: library, path: "Promo/Right")
    digested_file(left, filename: "preview.jpg", digest: "promo-img", size: 1024)
    digested_file(right, filename: "preview.jpg", digest: "promo-img", size: 1024)
    sized_file(left, filename: "mesh.stl", size: bytes_a - 1024)
    sized_file(right, filename: "mesh.stl", size: bytes_b - 1024)
    [left, right]
  end

  it "is about 0.00001 when a 1 KB image is shared against 100 MB and 200 MB" do
    left, right = promo_models(100_000_000, 200_000_000)
    ev = described_class.build(left, right)
    expect(ev.total_bytes_a).to eq(100_000_000)
    expect(ev.total_bytes_b).to eq(200_000_000)
    expect(ev.shared_bytes).to eq(1024)
    expect(ev.byte_containment).to be_within(1e-12).of(0.00001024)
  end

  it "is 1.0 when the smaller model's bytes are entirely shared" do
    small = create(:model, library: library, path: "Full/Small")
    large = create(:model, library: library, path: "Full/Large")
    digested_file(small, filename: "part.stl", digest: "contained", size: 50)
    digested_file(large, filename: "part.stl", digest: "contained", size: 50)
    digested_file(large, filename: "extra.stl", digest: "extra", size: 950)
    expect(described_class.build(small, large).byte_containment).to eq(1.0)
  end

  it "is 0.0 when both models have zero total bytes" do
    empty_a = create(:model, library: library, path: "Empty/A")
    empty_b = create(:model, library: library, path: "Empty/B")
    ev = described_class.build(empty_a, empty_b)
    expect(ev.total_bytes_a).to eq(0)
    expect(ev.total_bytes_b).to eq(0)
    expect(ev.byte_containment).to eq(0.0)
  end

  describe "containment facts" do
    it "is not lossless when both sides have unique files" do
      expect(evidence.lossless).to be(false)
      expect(evidence.contained_side).to eq("a")
      expect(evidence.container_side).to eq("b")
    end

    it "is lossless when every file of the smaller side exists in the larger" do
      stub = create(:model, library: library, path: "Pack/Stub", name: "Stub")
      digested_file(stub, filename: "common.jpg", digest: "aaa", size: 1000)
      contained = described_class.build(alpha, stub)
      expect(contained.lossless).to be(true)
      expect(contained.contained_side).to eq("b")
      expect(contained.container_side).to eq("a")
      expect(contained.contained_files_all_images).to be(true)
    end

    it "is not lossless when the smaller side has a file the larger lacks" do
      stub = create(:model, library: library, path: "Pack/Stub", name: "Stub")
      digested_file(stub, filename: "common.jpg", digest: "aaa", size: 500)
      digested_file(stub, filename: "only_here.jpg", digest: "zzz", size: 10)
      expect(described_class.build(alpha, stub).lossless).to be(false)
    end

    it "does not flag shared meshes as image-only" do
      expect(evidence.contained_files_all_images).to be(false)
    end
  end
end
