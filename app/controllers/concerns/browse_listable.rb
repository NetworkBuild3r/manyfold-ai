# frozen_string_literal: true

# Thin pagination prep for BrowseGrid indexes (creators / collections).
# Models keep ModelListable (filters, tags, has_image); this only owns page size + page=1 HTML.
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
      @browse_has_more = (offset + per_page) < total
      scope.offset(offset).limit(per_page)
    else
      page = if stream
        params[:page].presence || 1
      else
        1
      end
      result = scope.page(page).per(per_page)
      @browse_offset = (page.to_i - 1) * per_page
      @browse_has_more = result.next_page.present?
      result
    end
  end
end
