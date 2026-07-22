# frozen_string_literal: true

# Thin pagination prep for BrowseGrid indexes (creators / collections).
# Models keep ModelListable (filters, tags, has_image); this only owns page size + page=1 HTML.
module BrowseListable
  extend ActiveSupport::Concern

  private

  def prepare_browse_page(scope)
    per_page = BrowseGrid.page_size
    @browse_per_page = per_page

    page = if infinite_scroll_or_stream_request?
      params[:page].presence || 1
    else
      1
    end
    scope.page(page).per(per_page)
  end
end
