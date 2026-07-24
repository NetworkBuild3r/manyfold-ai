# frozen_string_literal: true

# Shared helpers for BrowseGrid-powered indexes (models / creators / collections).
# Infinite-scroll fetch URLs are built client-side from location.href; sentinels
# only need flags, totals, and offset metadata.
module BrowseHelper
  def browse_grid_page_size
    BrowseGrid.page_size
  end

  # path_helper: symbol like :models_path, :creators_path, :collections_path
  # Kept for non-scroll page links (e.g. models_page_url); not used by infinite scroll.
  def browse_page_url(path_helper, page, filter: nil, per_page: nil)
    size = per_page.presence || BrowseGrid.page_size
    base = filter&.to_params || {}
    sort = request.query_parameters.slice("order", "direction")
    public_send(path_helper, base.merge(page: page, per_page: size).merge(sort))
  end

  # Metadata for top/bottom sentinels (bidirectional row window).
  # path_helper / filter kept for call-site parity; fetch URLs are client-owned.
  def browse_window_meta(_path_helper, filter: nil) # rubocop:disable Lint/UnusedMethodArgument
    {
      has_more_after: ActiveModel::Type::Boolean.new.cast(@browse_has_more_after),
      has_more_before: ActiveModel::Type::Boolean.new.cast(@browse_has_more_before),
      total_count: @browse_total_count.to_i,
      offset: @browse_offset.to_i,
      returned: @browse_returned_count.to_i
    }
  end

  def creators_page_url(page, filter = nil, per_page: nil)
    browse_page_url(:creators_path, page, filter: filter, per_page: per_page)
  end

  def collections_page_url(page, filter = nil, per_page: nil)
    browse_page_url(:collections_path, page, filter: filter, per_page: per_page)
  end
end
