# frozen_string_literal: true

# Shared helpers for BrowseGrid-powered indexes (models / creators / collections).
module BrowseHelper
  def browse_grid_columns
    BrowseGrid.columns(pagination_settings)
  end

  def browse_grid_page_size
    BrowseGrid.page_size_for_settings(pagination_settings)
  end

  # path_helper: symbol like :models_path, :creators_path, :collections_path
  def browse_page_url(path_helper, page, filter: nil, per_page: nil)
    settings = pagination_settings
    cols = BrowseGrid.columns(settings)
    size = per_page.presence || BrowseGrid.page_size_for_settings(settings)
    size = BrowseGrid.aligned_page_size(size, cols)
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