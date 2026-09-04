# frozen_string_literal: true

require "rails_helper"
require "support/mock_directory"

# rubocop:disable RSpec/MultipleDescribes -- service + unmerge honesty share this file (INIT-019/SPEC-004)
RSpec.describe Model::Merge do
  around do |ex|
    MockDirectory.create([
      "parent/parent_part.stl",
      "parent/child/child_part.stl"
    ]) do |path|
      @library_path = path
      ex.run
    end
  end

  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable
  let!(:parent) { create(:model, library: library, path: "parent") }
  let!(:child) { create(:model, library: library, path: "parent/child") }
  let!(:parent_file) { create(:model_file, model: parent, filename: "parent_part.stl") }
  let!(:child_file) { create(:model_file, model: child, filename: "child_part.stl") }

  it "stamps ScanContext on target, sources, and model_files before writes" do
    seen = nil
    allow(ScanContext).to receive(:apply!).and_wrap_original do |method, *records|
      seen ||= records.flatten
      method.call(*records)
    end

    described_class.call(parent, child)

    expect(seen).to include(parent, child, parent_file, child_file)
  end

  it "does not enqueue CheckForProblemsJob" do
    expect { described_class.call(parent, child) }
      .not_to have_enqueued_job(Scan::Model::CheckForProblemsJob)
  end

  it "persists MergeHistory and removes the source when uniqueness Redlock would raise" do
    stub_unique_enqueue_redlock_error

    expect { parent.merge!(child) }.not_to raise_error

    expect(MergeHistory.where(target_model: parent).count).to eq 1
    expect(Model.where(id: child.id)).not_to exist
  end

  it "leaves global uniqueness on_redis_connection_error unset" do
    initializer = Rails.root.join("config/initializers/active_job_uniqueness.rb").read
    expect(initializer).not_to match(/^\s*config\.on_redis_connection_error\s*=/)
  end

  it "reattaches adopted files after commit so storage matches path_within_library" do # rubocop:todo RSpec/MultipleExpectations
    described_class.call(parent, child)
    parent.model_files.reload.each do |file|
      expect(file.attachment.id).to eq file.path_within_library
      expect(file.exists_on_storage?).to be true
    end
  end

  # INIT-019/SPEC-004 — parent/child keeps a relative prefix without `..`
  it "places nested child files under the child-relative prefix" do # rubocop:todo RSpec/MultipleExpectations
    described_class.call(parent, child)
    history = parent.merge_histories.last
    expect(history.path_prefix).to eq "child"
    expect(history.path_prefix).not_to include("..")
    expect(parent.model_files.reload.pluck(:filename)).to include("child/child_part.stl")
    merged = parent.model_files.find_by!(filename: "child/child_part.stl")
    expect(LibraryPathJail.within?(library.path, merged.path_within_library)).to be true
  end
end

RSpec.describe Model::Merge, "same-library siblings" do # rubocop:todo RSpec/DescribeMethod
  # INIT-019/SPEC-004 (ADR D-2): Category/A + Category/B must not use ../B
  around do |ex|
    MockDirectory.create([
      "Category/A/part_a.stl",
      "Category/B/part_b.stl"
    ]) do |path|
      @library_path = path
      ex.run
    end
  end

  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable
  let!(:model_a) { create(:model, library: library, path: "Category/A") }
  let!(:model_b) { create(:model, library: library, path: "Category/B") }
  let!(:file_a) { create(:model_file, model: model_a, filename: "part_a.stl") } # rubocop:disable RSpec/LetSetup
  let!(:file_b) { create(:model_file, model: model_b, filename: "part_b.stl") } # rubocop:disable RSpec/LetSetup

  it "merges with a basename prefix that never contains .." do # rubocop:todo RSpec/MultipleExpectations, RSpec/ExampleLength
    expect(model_a.compute_merge_prefix(model_b)).to eq "B"
    expect(model_a.compute_merge_prefix(model_b)).not_to include("..")

    described_class.call(model_a, model_b)

    history = model_a.merge_histories.last
    expect(history.path_prefix).to eq "B"
    expect(history.path_prefix).not_to include("..")
    expect(model_a.model_files.reload.pluck(:filename)).to include("B/part_b.stl")
    merged = model_a.model_files.find_by!(filename: "B/part_b.stl")
    expect(LibraryPathJail.within?(library.path, merged.path_within_library)).to be true
    expect(merged.exists_on_storage?).to be true
    expect(Model.where(id: model_b.id)).not_to exist
  end

  it "disambiguates colliding basename filenames via adopt_file" do # rubocop:todo RSpec/MultipleExpectations, RSpec/ExampleLength
    create(:model_file, model: model_a, filename: "B/part_b.stl", digest: "different")
    described_class.call(model_a, model_b)
    filenames = model_a.model_files.reload.pluck(:filename)
    expect(filenames).to include("B/part_b.stl")
    # Existing adopt_file collision flattens basename + digest/hex suffix
    expect(filenames.grep(/\Apart_b_.+\.stl\z/)).not_to be_empty
    model_a.model_files.reload.each do |file|
      expect(LibraryPathJail.within?(library.path, file.path_within_library)).to be true
    end
  end
end

RSpec.describe Model::Merge, "cross-library" do # rubocop:todo RSpec/DescribeMethod
  around do |ex|
    MockDirectory.create([
      "lib_a/target/keep.stl",
      "lib_b/other/source.stl"
    ]) do |path|
      @library_path = path
      ex.run
    end
  end

  let(:library_a) { create(:library, path: File.join(@library_path, "lib_a")) } # rubocop:todo RSpec/InstanceVariable
  let(:library_b) { create(:library, path: File.join(@library_path, "lib_b")) } # rubocop:todo RSpec/InstanceVariable
  let!(:target) { create(:model, library: library_a, path: "target") }
  let!(:source) { create(:model, library: library_b, path: "other") }
  let!(:source_file) { create(:model_file, model: source, filename: "source.stl") } # rubocop:disable RSpec/LetSetup

  it "uses basename for cross-library merges" do # rubocop:todo RSpec/MultipleExpectations
    expect(target.compute_merge_prefix(source)).to eq "other"
    described_class.call(target, source)
    expect(target.merge_histories.last.path_prefix).to eq "other"
    expect(target.model_files.reload.pluck(:filename)).to include("other/source.stl")
  end
end

RSpec.describe Model::Merge, "rollback after adopt" do # rubocop:todo RSpec/DescribeMethod
  around do |ex|
    MockDirectory.create([
      "root/target/keep.stl",
      "root/source/part.stl"
    ]) do |path|
      @library_path = path
      ex.run
    end
  end

  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable
  let!(:target) { create(:model, library: library, path: "root/target") }
  let!(:source) { create(:model, library: library, path: "root/source") }
  let!(:source_file) { create(:model_file, model: source, filename: "part.stl") }

  it "rolls back source file rows and leaves source storage at the old path" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
    old_path = source_file.path_within_library
    old_attachment_id = source_file.attachment.id
    expect(library.has_file?(old_path)).to be true
    allow(MergeHistory).to receive(:create!).and_raise("forced rollback")

    expect { described_class.call(target, source) }.to raise_error("forced rollback")

    expect(source.reload.model_files.count).to eq 1
    expect(MergeHistory.where(target_model: target).count).to eq 0
    source_file.reload
    expect(source_file.attachment.id).to eq old_attachment_id
    expect(library.has_file?(old_path)).to be true
    expect(source_file.exists_on_storage?).to be true
  end
end

RSpec.describe Model::Unmerge, "partial restore honesty" do # rubocop:todo RSpec/DescribeMethod
  # INIT-019/SPEC-004 (ADR D-2): missing files must not set undone_at
  around do |ex|
    MockDirectory.create([
      "parent/parent_part.stl",
      "parent/child/child_part.stl",
      "parent/child/extra.stl"
    ]) do |path|
      @library_path = path
      ex.run
    end
  end

  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable
  let!(:parent) { create(:model, library: library, path: "parent") }
  let!(:child) { create(:model, library: library, path: "parent/child") }

  before do
    create(:model_file, model: child, filename: "child_part.stl")
    create(:model_file, model: child, filename: "extra.stl")
    parent.merge!(child)
  end

  it "leaves undone_at nil when one or more history files cannot be placed" do # rubocop:todo RSpec/MultipleExpectations, RSpec/ExampleLength
    history = parent.merge_histories.last
    moved = history.moved_files
    # Simulate a missing file (deleted after merge) so placement skips
    gone = ModelFile.find(moved.first["id"])
    gone.destroy!
    history.reload

    new_model = described_class.call(parent, history)

    history.reload
    expect(history.undone_at).to be_nil
    expect(new_model).to be_persisted
    # Retry remains available — undone_at still nil so "already undone" does not fire
    expect { described_class.call(parent, history.reload) }.not_to raise_error
  end

  it "sets undone_at when every history file is placed" do # rubocop:todo RSpec/MultipleExpectations
    history = parent.merge_histories.last
    described_class.call(parent, history)
    expect(history.reload.undone_at).to be_present
  end
end
# rubocop:enable RSpec/MultipleDescribes
