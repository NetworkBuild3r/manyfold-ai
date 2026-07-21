# frozen_string_literal: true

# Thin pagination prep for BrowseGrid indexes (creators / collections).
# Models keep ModelListable (filters, tags, has_image); this only owns page size + page=1 HTML.
module BrowseListable
  extend ActiveSupport::Concern

  private

  def prepare_browse_page(scope)
    settings = helpers.pagination_settings
    cols = BrowseGrid.columns(settings)
    preferred = if infinite_scroll_or_stream_request? && params[:per_page].present?
      params[:per_page]
    else
      settings["per_page"]
    end
    per_page = BrowseGrid.aligned_page_size(preferred, cols)
    @browse_columns = cols
    @browse_per_page = per_page

    page = if infinite_scroll_or_stream_request?
      params[:page].presence || 1
    else
      1
    end
    scope.page(page).per(per_page)
  end
end
