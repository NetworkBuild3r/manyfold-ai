# frozen_string_literal: true

require "rails_helper"

RSpec.describe BrowseHelper, type: :helper do
  describe "#browse_window_meta" do
    before do
      helper.instance_variable_set(:@browse_offset, 12)
      helper.instance_variable_set(:@browse_per_page, 5)
      helper.instance_variable_set(:@browse_returned_count, 5)
      helper.instance_variable_set(:@browse_total_count, 40)
      helper.instance_variable_set(:@browse_has_more_after, true)
      helper.instance_variable_set(:@browse_has_more_before, true)
    end

    it "returns flags and totals without continuation URLs" do
      meta = helper.browse_window_meta(:creators_path)
      expect(meta).to eq(
        has_more_after: true,
        has_more_before: true,
        total_count: 40,
        offset: 12,
        returned: 5
      )
      expect(meta).not_to have_key(:next_url)
      expect(meta).not_to have_key(:prev_url)
    end

    it "casts boolean-ish has_more flags" do
      helper.instance_variable_set(:@browse_has_more_after, "false")
      helper.instance_variable_set(:@browse_has_more_before, "0")
      meta = helper.browse_window_meta(:models_path)
      expect(meta[:has_more_after]).to be false
      expect(meta[:has_more_before]).to be false
    end
  end
end
