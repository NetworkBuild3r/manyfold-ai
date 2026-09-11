# frozen_string_literal: true

# Shared helpers for BrowseGrid-powered indexes (models / creators / collections).
# Infinite-scroll fetch URLs are built client-side from location.href; sentinels
# only need flags, totals, and offset metadata.
module BrowseHelper
  def browse_grid_page_size
    BrowseGrid.page_size
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
end
