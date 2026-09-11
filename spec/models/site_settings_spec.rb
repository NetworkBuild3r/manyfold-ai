require "rails_helper"

RSpec.describe SiteSettings do
  context "when detecting ignored files" do
    %w[
      ./test.stl
      /test.stl
      test.stl
      test/test.stl
    ].each do |pathname|
      it "accepts `#{pathname}`" do
        expect(described_class.send(:ignored_file?, pathname)).to be false
      end
    end

    %w[
      .test.stl
      test/.test.stl
      .test/test.stl
      model/@eaDir/test.png/SYNOPHOTO_THUMB_S.png
      model/__MACOSX
    ].each do |pathname|
      it "ignores `#{pathname}`" do
        expect(described_class.send(:ignored_file?, pathname)).to be true
      end
    end
  end

  # INIT-027/SPEC-005
  describe "appearance accent" do
    it "exposes all five AVAILABLE_ACCENTS including indigo" do
      expect(described_class::AVAILABLE_ACCENTS).to eq %w[indigo green purple amber rose]
    end

    it "returns a listed accent unchanged" do
      described_class.accent_color = "rose"
      expect(described_class.validated_accent_color).to eq "rose"
    end

    it "falls back to indigo when the stored value is unknown" do
      described_class.accent_color = "not-a-color"
      expect(described_class.validated_accent_color).to eq "indigo"
    end
  end
end
