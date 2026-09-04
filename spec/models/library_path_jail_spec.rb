# frozen_string_literal: true

require "rails_helper"

# INIT-019/SPEC-002 — shared library path jail helper (ADR D-1)
RSpec.describe LibraryPathJail do
  let(:library_root) { Dir.mktmpdir("library_path_jail") }

  after { FileUtils.remove_entry(library_root) }

  describe ".within?" do
    it "allows nested relative members under the library" do
      expect(described_class.within?(library_root, "sub/dir/model.stl")).to be true
    end

    it "rejects parent-directory segments even when expand would stay inside" do
      expect(described_class.within?(library_root, "model/../sibling.stl")).to be false
    end

    it "rejects absolute paths including drive-letter forms" do
      expect(described_class.within?(library_root, "/etc/passwd.stl")).to be false
      expect(described_class.unsafe_relative?("C:\\Windows\\x.stl")).to be true
    end

    it "rejects NUL bytes in relative paths" do
      expect(described_class.unsafe_relative?("evil\0.stl")).to be true
    end

    it "rejects expands that leave the library root" do
      expect(described_class.within?(library_root, "../outside.stl")).to be false
    end

    it "does not treat a sibling prefix as inside the library" do
      sibling = "#{library_root}-evil"
      FileUtils.mkdir_p(sibling)
      begin
        expect(described_class.contained?(library_root, File.join(sibling, "x.stl"))).to be false
      ensure
        FileUtils.remove_entry(sibling)
      end
    end
  end

  describe ".assert_within!" do
    it "returns the relative path when jailed" do
      expect(described_class.assert_within!(library_root, "a/b.stl")).to eq "a/b.stl"
    end

    it "raises EscapeError when the path escapes" do
      expect {
        described_class.assert_within!(library_root, "../escape.stl")
      }.to raise_error(LibraryPathJail::EscapeError)
    end
  end
end
