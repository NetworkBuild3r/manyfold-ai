# frozen_string_literal: true

require "rails_helper"

RSpec.describe LibraryFileSystem do
  it "moves bytes without applying shrine file permissions" do
    Dir.mktmpdir("library_fs") do |dir|
      source = File.join(dir, "src.bin")
      File.binwrite(source, "payload")
      storage = described_class.new(dir)
      File.open(source, "rb") { |io| storage.upload(io, "dest.bin", move: true) }
      expect(File.binread(File.join(dir, "dest.bin"))).to eq "payload"
      expect(storage.permissions).to be_nil
    end
  end
end
