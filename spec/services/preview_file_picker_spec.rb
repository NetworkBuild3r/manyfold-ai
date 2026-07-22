# frozen_string_literal: true

require "rails_helper"
require "support/mock_directory"

RSpec.describe PreviewFilePicker do
  around do |ex|
    MockDirectory.create([
      "m/preview.jpg",
      "m/other.png",
      "m/part.stl",
      "m/gone.jpg"
    ]) do |path|
      @library_path = path
      File.delete(File.join(path, "m/gone.jpg"))
      ex.run
    end
  end

  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable
  let(:model) { create(:model, library: library, path: "m") }

  def add_files(*names)
    names.map { |n| create(:model_file, model: model, filename: n) }
  end

  it "keeps an existing on-disk image preview" do
    other, preview = add_files("other.png", "preview.jpg")
    model.update!(preview_file: other)
    expect(described_class.new(model).call).to eq other
  end

  it "prefers preview/cover/thumb names when assigning" do
    add_files("other.png", "preview.jpg", "part.stl")
    expect(described_class.new(model).call.filename).to eq "preview.jpg"
  end

  it "upgrades nil preview to an on-disk image" do
    add_files("other.png", "part.stl")
    expect(described_class.new(model).call.filename).to eq "other.png"
  end

  it "upgrades a mesh preview to an on-disk image" do
    stl, = add_files("part.stl", "cover.jpg")
    model.update!(preview_file: stl)
    expect(described_class.new(model).call.filename).to eq "cover.jpg"
  end

  it "replaces a missing image with an on-disk image" do
    gone, present = add_files("gone.jpg", "other.png")
    model.update!(preview_file: gone)
    expect(described_class.new(model).call).to eq present
  end

  it "returns nil with require_on_disk when no image is on disk" do
    gone, = add_files("gone.jpg")
    model.update!(preview_file: gone)
    expect(described_class.new(model).call(require_on_disk: true)).to be_nil
  end

  it "falls back to mesh when no images exist" do
    add_files("part.stl")
    expect(described_class.new(model).call.filename).to eq "part.stl"
  end
end
