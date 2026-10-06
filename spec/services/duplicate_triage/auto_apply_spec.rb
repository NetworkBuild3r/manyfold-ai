# frozen_string_literal: true

require "rails_helper"

RSpec.describe DuplicateTriage::AutoApply, type: :duplicate_triage do
  let(:library) { create(:library) }
  let(:prompt_version) { DuplicateTriage::LlmJudge::PROMPT_VERSION }

  # Container (bigger) has aaa+bbb; stub has only aaa, an image → lossless, container is the keeper.
  def lossless_pair(name, container_path: nil, stub_path: nil)
    container = create(:model, library: library, path: container_path || "Auto/#{name}", name: name)
    stub = create(:model, library: library, path: stub_path || "Auto/#{name} Stub", name: "#{name} Stub")
    digested_file(container, filename: "pack.zip", digest: "aaa-#{name}", size: 1000)
    digested_file(container, filename: "extra.stl", digest: "bbb-#{name}", size: 500)
    digested_file(stub, filename: "pack.zip", digest: "aaa-#{name}", size: 1000)
    [container, stub]
  end

  def verdict_for(left, right, overrides = {})
    evidence = DuplicateTriage::Evidence.build(left, right)
    low, high = [left, right].minmax_by(&:id)
    attributes = {
      model_a: low, model_b: high, fingerprint: evidence.fingerprint, prompt_version: prompt_version,
      evidence: evidence.to_prompt_h, confidence: 0.95, reason: "same product"
    }
    create(:duplicate_pair_verdict, **attributes.merge(overrides))
  end

  before do
    allow(Model::MergeWithChoices).to receive(:call)
  end

  it "does nothing by default (dry run) and leaves the verdict proposed" do
    container, stub = lossless_pair("Dry")
    verdict = verdict_for(container, stub)
    summary = described_class.call(pace: 0)
    expect(summary.would_apply).to eq(1)
    expect(summary.applied).to eq(0)
    expect(Model::MergeWithChoices).not_to have_received(:call)
    expect(verdict.reload).to be_proposed
  end

  it "merges the stub into the larger entry" do
    container, stub = lossless_pair("Go")
    verdict_for(container, stub)
    summary = described_class.call(dry_run: false, pace: 0)
    expect(summary.applied).to eq(1)
    expect(Model::MergeWithChoices).to have_received(:call).with(
      hash_including(target: container, source: stub, tag_strategy: "combine")
    )
  end

  it "picks the keeper from evidence even when the model said the other side" do
    container, stub = lossless_pair("Keeper")
    verdict_for(container, stub, keeper: (container.id < stub.id) ? "b" : "a")
    described_class.call(dry_run: false, pace: 0)
    expect(Model::MergeWithChoices).to have_received(:call).with(hash_including(target: container))
  end

  it "fills blank target fields from the source and ORs sensitive" do
    container, stub = lossless_pair("Fill")
    container.update!(caption: nil)
    stub.update!(caption: "From stub", sensitive: true)
    verdict_for(container, stub)
    described_class.call(dry_run: false, pace: 0)
    expect(Model::MergeWithChoices).to have_received(:call).with(
      hash_including(
        choices: hash_including("caption" => "b", "name" => "a", "sensitive" => "override"),
        overrides: {"sensitive" => true}
      )
    )
  end

  it "breaks a byte tie with the most files, then the older model (D-7)" do
    older = create(:model, library: library, path: "Auto/TieOld", name: "TieOld", created_at: 2.days.ago)
    newer = create(:model, library: library, path: "Auto/TieNew", name: "TieNew")
    [older, newer].each { |model| digested_file(model, filename: "same.zip", digest: "tie", size: 700) }
    verdict_for(older, newer)
    described_class.call(dry_run: false, pace: 0)
    expect(Model::MergeWithChoices).to have_received(:call).with(hash_including(target: older, source: newer))
  end

  it "rejects the verdict when the evidence changed after judging" do
    container, stub = lossless_pair("Changed")
    verdict = verdict_for(container, stub)
    digested_file(stub, filename: "new.stl", digest: "new-file", size: 5)
    summary = described_class.call(dry_run: false, pace: 0)
    expect(summary.rejected).to eq(1)
    expect(verdict.reload).to be_rejected
    expect(verdict.error).to eq("evidence_changed")
    expect(Model::MergeWithChoices).not_to have_received(:call)
  end

  it "rejects a pair that is no longer lossless" do
    container, stub = lossless_pair("Lossy")
    verdict = verdict_for(container, stub)
    # a stored lossless flag on a pair whose files are not actually contained (stale or tampered row)
    other = create(:model, library: library, path: "Auto/LossyOther", name: "LossyOther")
    digested_file(other, filename: "pack.zip", digest: "aaa-Lossy", size: 1000)
    digested_file(other, filename: "extra.stl", digest: "ccc-Lossy", size: 100)
    lossy = verdict_for(container, other, evidence: {"lossless" => true})
    summary = described_class.call(dry_run: false, pace: 0)
    expect(summary.rejected).to eq(1)
    expect(summary.applied).to eq(1)
    expect(lossy.reload.error).to eq("not_lossless")
    expect(verdict.reload).to be_proposed
  end

  it "never selects verdicts stored as not lossless, low confidence, other prompt versions or non-merge" do
    container, stub = lossless_pair("Filtered")
    verdict_for(container, stub, evidence: {"lossless" => false})
    c2, s2 = lossless_pair("LowConf")
    verdict_for(c2, s2, confidence: 0.85)
    c3, s3 = lossless_pair("OldPrompt")
    verdict_for(c3, s3, prompt_version: "v1")
    c4, s4 = lossless_pair("Separate")
    verdict_for(c4, s4, decision: :keep_separate)
    summary = described_class.call(dry_run: false, pace: 0)
    expect(summary.to_h.values_at(:applied, :rejected, :skipped, :would_apply)).to eq([0, 0, 0, 0])
    expect(Model::MergeWithChoices).not_to have_received(:call)
  end

  it "leaves a pair alone when a human verdict exists for the same fingerprint" do
    container, stub = lossless_pair("Human")
    verdict = verdict_for(container, stub)
    create(
      :duplicate_pair_verdict, :human,
      model_a: verdict.model_a, model_b: verdict.model_b, fingerprint: verdict.fingerprint, decision: :keep_separate
    )
    summary = described_class.call(dry_run: false, pace: 0)
    expect(summary.skipped).to eq(1)
    expect(Model::MergeWithChoices).not_to have_received(:call)
  end

  it "rejects nested ancestor/descendant pairs" do
    container, stub = lossless_pair("Nest", container_path: "Nest/Parent", stub_path: "Nest/Parent/Child")
    verdict = verdict_for(container, stub)
    described_class.call(dry_run: false, pace: 0)
    expect(verdict.reload.error).to eq("nested")
    expect(Model::MergeWithChoices).not_to have_received(:call)
  end

  it "stops after three consecutive merge failures and marks them rejected" do
    allow(Model::MergeWithChoices).to receive(:call).and_raise(Errno::EIO)
    verdicts = Array.new(4) { |i| verdict_for(*lossless_pair("Fail#{i}")) }
    summary = described_class.call(dry_run: false, pace: 0)
    expect(summary.failed).to eq(3)
    expect(summary.stopped).to be(true)
    expect(verdicts.count { |v| v.reload.rejected? }).to eq(3)
  end

  it "caps the number of merges per run" do
    2.times { |i| verdict_for(*lossless_pair("Cap#{i}")) }
    summary = described_class.call(limit: 1, dry_run: false, pace: 0)
    expect(summary.applied).to eq(1)
  end
end
