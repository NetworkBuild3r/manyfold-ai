# frozen_string_literal: true

# Thin pagination prep for BrowseGrid indexes (creators / collections).
module BrowseListable
  extend ActiveSupport::Concern

  private

  def prepare_browse_page(scope)
    stream = infinite_scroll_or_stream_request?
    per_page = BrowseGrid.page_size_for_request(params, stream: stream)
    @browse_per_page = per_page

    if stream && params[:offset].present?
      offset = BrowseGrid.offset_for_request(params)
      @browse_offset = offset
      total = scope.count
      @browse_total_count = total
      result = scope.offset(offset).limit(per_page)
      records = result.load
      @browse_returned_count = records.size
      @browse_has_more_after = (offset + records.size) < total
      @browse_has_more_before = offset.positive?
      @browse_window = params[:window].presence_in(%w[before after]) || "after"
      result
    else
      page = if stream
        params[:page].presence || 1
      else
        1
      end
      result = scope.page(page).per(per_page)
      @browse_offset = (page.to_i - 1) * per_page
      @browse_total_count = result.total_count
      @browse_returned_count = result.size
      @browse_has_more_after = result.next_page.present?
      @browse_has_more_before = page.to_i > 1
      @browse_window = "after"
      result
    end
  end
end
