# frozen_string_literal: true

require "rails_helper"
require "support/mock_directory"

RSpec.describe Scan::ApplySparkMergePlanJob do
  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable

  around do |ex|
    MockDirectory.create([
      "DC/Batman Pack/model.stl",
      "DC/Batman Pack/preview.jpg",
      "DC/Batman Pack (2)/model.stl",
      "DC/Batman Pack (2)/extra.stl",
      "DC/Other Batman/model.stl"
    ]) do |path|
      @library_path = path
      FileUtils.mkdir_p(File.join(path, ".spark-curate"))
      ex.run
    end
  end

  def write_pending(rows)
    path = File.join(library.path, ".spark-curate", "merges-pending.jsonl")
    File.write(path, rows.map { |r| JSON.generate(r) }.join("\n") + "\n")
  end

  it "dry-run does not merge models" do
    target = create(:model, library: library, path: "DC/Batman Pack", name: "Batman Pack")
    source = create(:model, library: library, path: "DC/Batman Pack (2)", name: "Batman Pack (2)")
    create(:model_file, model: target, filename: "model.stl")
    create(:model_file, model: source, filename: "model.stl")
    create(:model_file, model: source, filename: "extra.stl")

    write_pending([{
      "path_a" => "DC/Batman Pack",
      "path_b" => "DC/Batman Pack (2)",
      "target" => "a",
      "confidence" => 0.92,
      "reason" => "duplicate download"
    }])

    expect {
      described_class.perform_now(library_id: library.id, dry_run: true)
    }.not_to change(Model, :count)

    expect(Model.exists?(source.id)).to be true
    expect(File).to exist(File.join(library.path, ".spark-curate", "merges-pending.jsonl"))
  end

  it "applies merge when confidence >= 0.80 and paths exist" do
    target = create(:model, library: library, path: "DC/Batman Pack", name: "Batman Pack")
    source = create(:model, library: library, path: "DC/Batman Pack (2)", name: "Batman Pack (2)")
    create(:model_file, model: target, filename: "model.stl")
    create(:model_file, model: source, filename: "extra.stl")

    write_pending([{
      "path_a" => "DC/Batman Pack",
      "path_b" => "DC/Batman Pack (2)",
      "target" => "a",
      "confidence" => 0.91,
      "reason" => "name near dupe"
    }])

    result = described_class.perform_now(library_id: library.id, dry_run: false, limit: 10)
    expect(result[:applied]).to eq 1
    expect(Model.exists?(source.id)).to be false
    expect(target.reload.model_files.map(&:filename)).to include("extra.stl")
    expect(MergeHistory.where(target_model: target).count).to eq 1
  end

  it "skips records below confidence 0.80" do
    create(:model, library: library, path: "DC/Batman Pack")
    create(:model, library: library, path: "DC/Batman Pack (2)")

    write_pending([{
      "path_a" => "DC/Batman Pack",
      "path_b" => "DC/Batman Pack (2)",
      "target" => "a",
      "confidence" => 0.5,
      "reason" => "unsure"
    }])

    result = described_class.perform_now(library_id: library.id, dry_run: false)
    expect(result[:applied]).to eq 0
    expect(result[:skipped]).to be >= 1
  end

  it "does not merge when a path is missing from the DB" do
    create(:model, library: library, path: "DC/Batman Pack")

    write_pending([{
      "path_a" => "DC/Batman Pack",
      "path_b" => "DC/Missing",
      "target" => "a",
      "confidence" => 0.95,
      "reason" => "should skip"
    }])

    result = described_class.perform_now(library_id: library.id, dry_run: false)
    expect(result[:applied]).to eq 0
  end
end
