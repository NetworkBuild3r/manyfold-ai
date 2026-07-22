# frozen_string_literal: true

# Shared helpers for BrowseGrid-powered indexes (models / creators / collections).
module BrowseHelper
  def browse_grid_page_size
    BrowseGrid.page_size
  end

  # path_helper: symbol like :models_path, :creators_path, :collections_path
  def browse_page_url(path_helper, page, filter: nil, per_page: nil)
    size = per_page.presence || BrowseGrid.page_size
    base = filter&.to_params || {}
    sort = request.query_parameters.slice("order", "direction")
    public_send(path_helper, base.merge(page: page, per_page: size).merge(sort))
  end

  def creators_page_url(page, filter = nil, per_page: nil)
    browse_page_url(:creators_path, page, filter: filter, per_page: per_page)
  end

  def collections_page_url(page, filter = nil, per_page: nil)
    browse_page_url(:collections_path, page, filter: filter, per_page: per_page)
  end
end
