# frozen_string_literal: true

require "rails_helper"

RSpec.describe DuplicateTriage::Pairs, type: :duplicate_triage do
  let(:library) { create(:library) }

  def pairs
    described_class.new.to_a
  end

  describe "a 3-model digest group (AC1)" do
    let!(:keeper) { create(:model, library: library, path: "Group/Keeper", name: "Keeper") }
    let!(:other_a) { create(:model, library: library, path: "Group/OtherA", name: "Other A") }
    let!(:other_b) { create(:model, library: library, path: "Group/OtherB", name: "Other B") }

    before do
      digested_file(keeper, filename: "shared.stl", digest: "group3", size: 100)
      digested_file(keeper, filename: "k2.stl", digest: "k-two", size: 20)
      digested_file(keeper, filename: "k3.stl", digest: "k-three", size: 20)
      digested_file(other_a, filename: "shared.stl", digest: "group3", size: 100)
      digested_file(other_b, filename: "shared.stl", digest: "group3", size: 100)
    end

    it "emits two pairs against the same keeper" do
      expect(pairs.size).to eq(2)
      expect(pairs.map(&:keeper).uniq).to eq([keeper])
    end

    it "does not emit a pair between the two non-keepers" do
      ids = pairs.map { |pair| [pair.model_a.id, pair.model_b.id] }
      expect(ids).to contain_exactly(
        [keeper.id, other_a.id].minmax,
        [keeper.id, other_b.id].minmax
      )
    end
  end

  describe "keeper tie-break (D-7)" do
    let!(:older) { create(:model, library: library, path: "Tie/Older", name: "Older") }
    let!(:newer) { create(:model, library: library, path: "Tie/Newer", name: "Newer") }

    before do
      older.update_column(:created_at, 2.days.ago)
      newer.update_column(:created_at, 1.day.ago)
      digested_file(older, filename: "shared.stl", digest: "tie", size: 50)
      digested_file(newer, filename: "shared.stl", digest: "tie", size: 50)
    end

    it "picks the older created_at when file counts match" do
      expect(pairs.map(&:keeper)).to eq([older])
    end
  end

  describe "non-pairs" do
    it "ignores same-model extras" do
      lone = create(:model, library: library, path: "Noise/Lone")
      digested_file(lone, filename: "a.stl", digest: "same-model", size: 10)
      digested_file(lone, filename: "b.stl", digest: "same-model", size: 10)
      expect(pairs).to be_empty
    end

    it "ignores zero-size and blank-digest files" do
      left = create(:model, library: library, path: "Noise/Left")
      right = create(:model, library: library, path: "Noise/Right")
      digested_file(left, filename: "empty.stl", digest: "empty-size", size: 0)
      digested_file(right, filename: "empty.stl", digest: "empty-size", size: 0)
      digested_file(left, filename: "blank.stl", digest: "", size: 10)
      digested_file(right, filename: "blank.stl", digest: "", size: 10)
      expect(pairs).to be_empty
    end
  end

  it "contains no name-matching decisions under app/services/duplicate_triage (AC5)" do
    root = Rails.root.join("app/services/duplicate_triage")
    hits = Dir.glob(root.join("**/*.rb")).flat_map do |path|
      File.readlines(path).each_with_index.filter_map do |line, index|
        "#{path}:#{index + 1}" if line =~ /name.*=~|match\?/
      end
    end
    expect(hits).to eq([])
  end
end
