# frozen_string_literal: true

require "rails_helper"
require "webmock/rspec"

RSpec.describe DuplicateTriage::JudgeJob, type: :duplicate_triage do
  let(:library) { create(:library) }
  let(:endpoint) { "http://192.168.11.161:11434/v1" }
  let(:completions) { "#{endpoint}/chat/completions" }
  let(:ok_json) do
    {
      decision: "keep_separate",
      keeper: "a",
      confidence: 0.8,
      reason: "shared preview only"
    }.to_json
  end

  def isolated_pair(name, shared_size:, extra_a: 0, extra_b: 0, promo: false)
    left = create(:model, library: library, path: "Iso/#{name}A", name: "#{name}A")
    right = create(:model, library: library, path: "Iso/#{name}B", name: "#{name}B")
    digest = "iso-#{name}"
    if promo
      digested_file(left, filename: "preview.jpg", digest: digest, size: shared_size)
      digested_file(right, filename: "preview.jpg", digest: digest, size: shared_size)
      sized_file(left, filename: "mesh.stl", size: extra_a)
      sized_file(right, filename: "mesh.stl", size: extra_b)
    else
      digested_file(left, filename: "shared.stl", digest: digest, size: shared_size)
      digested_file(right, filename: "shared.stl", digest: digest, size: shared_size)
      digested_file(left, filename: "a.stl", digest: "ua-#{name}", size: extra_a) if extra_a.positive?
      digested_file(right, filename: "b.stl", digest: "ub-#{name}", size: extra_b) if extra_b.positive?
    end
    [left, right]
  end

  def stub_judge_calls
    allow(DuplicateTriage::LlmJudge).to receive(:configure!)
    allow(DuplicateTriage::LlmJudge).to receive(:model_id).and_return("test")
  end

  def keep_separate_result
    DuplicateTriage::LlmJudge::Result.new(
      decision: "keep_separate", keeper: "a", confidence: 0.5, reason: "ok", error: nil
    )
  end

  def containment(payload)
    payload[:byte_containment] || payload["byte_containment"]
  end

  # Create Low → Mid → High so Pairs id order is the opposite of AC5.
  def reverse_containment_pairs
    isolated_pair("Low", shared_size: 1024, extra_a: 100_000_000, extra_b: 200_000_000, promo: true)
    isolated_pair("Mid", shared_size: 500, extra_a: 500, extra_b: 500)
    isolated_pair("High", shared_size: 1000)
  end

  def stub_ok
    stub_request(:post, completions).to_return(
      status: 200,
      headers: {"Content-Type" => "application/json"},
      body: {choices: [{message: {content: ok_json}}]}.to_json
    )
  end

  around do |example|
    VCR.turned_off { example.run }
  end

  before do
    WebMock.disable_net_connect!
    ENV["DUPLICATE_TRIAGE_LLM_URL"] = endpoint
    ENV["DUPLICATE_TRIAGE_LLM_MODEL"] = "Qwen/Qwen3.8-Flash-Next"
    stub_const("#{described_class}::BATCH_PAUSE_SECONDS", 0)
    stub_const("#{described_class}::DEFAULT_CONCURRENCY", 1)
  end

  after do
    ENV.delete("DUPLICATE_TRIAGE_LLM_URL")
    ENV.delete("DUPLICATE_TRIAGE_LLM_MODEL")
  end

  it "raises ConfigurationError and writes nothing when env is unset (AC1)" do
    isolated_pair("One", shared_size: 100)
    ENV.delete("DUPLICATE_TRIAGE_LLM_URL")
    ENV.delete("DUPLICATE_TRIAGE_LLM_MODEL")
    expect { described_class.perform_now }.to raise_error(DuplicateTriage::ConfigurationError)
    expect(DuplicatePairVerdict.count).to eq(0)
  end

  it "stores unsure with error when the model adds an extra field (AC2)" do
    isolated_pair("Xtra", shared_size: 100)
    content = JSON.parse(ok_json).merge("note" => "nope").to_json
    stub_request(:post, completions).to_return(
      status: 200,
      body: {choices: [{message: {content: content}}]}.to_json
    )
    described_class.perform_now
    row = DuplicatePairVerdict.find_by(source: :llm)
    expect(row).to be_decision_unsure
    expect(row.error).to include("extra_field")
  end

  it "makes zero HTTP calls on a rerun of the same fingerprint (AC3)" do
    isolated_pair("Idem", shared_size: 100)
    stub_ok
    described_class.perform_now
    # one request per presentation order (a/b, then swapped)
    expect(WebMock).to have_requested(:post, completions).twice
    described_class.perform_now
    expect(WebMock).to have_requested(:post, completions).twice
  end

  it "skips a pair that already has a human verdict for this fingerprint" do
    left, right = isolated_pair("Human", shared_size: 100)
    evidence = DuplicateTriage::Evidence.build(left, right)
    create(
      :duplicate_pair_verdict, :human,
      model_a: left, model_b: right, fingerprint: evidence.fingerprint
    )
    stub_ok
    described_class.perform_now
    expect(WebMock).not_to have_requested(:post, completions)
  end

  it "does not send nested ancestry pairs to the LLM" do
    parent = create(:model, library: library, path: "Nest/Parent", name: "Parent")
    child = create(:model, library: library, path: "Nest/Parent/Child", name: "Child")
    digested_file(parent, filename: "shared.stl", digest: "nested", size: 80)
    digested_file(child, filename: "shared.stl", digest: "nested", size: 80)
    stub_ok
    described_class.perform_now
    expect(WebMock).not_to have_requested(:post, completions)
  end

  it "processes pairs by byte_containment descending and still judges below 0.01 (AC5)" do
    reverse_containment_pairs
    stub_judge_calls
    order = []
    allow(DuplicateTriage::LlmJudge).to receive(:consensus) do |payload|
      order << containment(payload)
      keep_separate_result
    end
    described_class.perform_now
    expect(order.size).to eq(3)
    expect(order[0]).to eq(1.0)
    expect(order[1]).to eq(0.5)
    expect(order[2]).to be < 0.01
    expect(order).to eq([1.0, 0.5, order.last])
  end

  it "judges the below-0.01 band after higher overlap at concurrency 8 (AC5)" do
    stub_const("#{described_class}::DEFAULT_CONCURRENCY", 8)
    reverse_containment_pairs
    stub_judge_calls
    lock = Mutex.new
    high_finish = []
    low_start = nil
    allow(DuplicateTriage::LlmJudge).to receive(:consensus) do |payload|
      value = containment(payload)
      if value >= 0.01
        sleep 0.05
        lock.synchronize { high_finish << Process.clock_gettime(Process::CLOCK_MONOTONIC) }
      else
        lock.synchronize { low_start = Process.clock_gettime(Process::CLOCK_MONOTONIC) }
      end
      keep_separate_result
    end
    described_class.perform_now
    expect(high_finish.size).to eq(2)
    expect(low_start).not_to be_nil
    expect(low_start).to be >= high_finish.max
  end

  it "enqueues from the judge rake task" do
    task = Rake::Task["manyfold:duplicate_triage:judge"]
    task.reenable
    expect { task.invoke("2") }.to have_enqueued_job(described_class).with(2)
  end
end
