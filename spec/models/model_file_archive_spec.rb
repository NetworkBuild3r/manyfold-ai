require "rails_helper"

RSpec.describe ModelFile do
  describe "#is_archive?" do
    it "is true for zip extension" do
      expect(build(:model_file, filename: "pack.zip").is_archive?).to be true
    end

    it "is false for stl" do
      expect(build(:model_file, filename: "part.stl").is_archive?).to be false
    end
  end
end
