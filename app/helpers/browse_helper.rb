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

  # window: "before" | "after" — scroll direction (not sort direction).
  def browse_continue_url(path_helper, filter: nil, offset:, per_page:, window: nil)
    base = filter&.to_params || {}
    sort = request.query_parameters.slice("order", "direction")
    params = base.merge(offset: offset, per_page: per_page).merge(sort)
    params[:window] = window if window.present?
    public_send(path_helper, params)
  end

  # Metadata for top/bottom sentinels (bidirectional row window).
  def browse_window_meta(path_helper, filter: nil)
    offset = @browse_offset.to_i
    per_page = @browse_per_page.to_i
    returned = @browse_returned_count.to_i
    total = @browse_total_count.to_i
    has_more_after = ActiveModel::Type::Boolean.new.cast(@browse_has_more_after)
    has_more_before = ActiveModel::Type::Boolean.new.cast(@browse_has_more_before)

    next_url = if has_more_after
      browse_continue_url(
        path_helper,
        filter: filter,
        offset: offset + returned,
        per_page: per_page,
        window: "after"
      )
    else
      ""
    end

    prev_url = if has_more_before
      prev_offset = [offset - per_page, 0].max
      prev_limit = [per_page, offset].min
      browse_continue_url(
        path_helper,
        filter: filter,
        offset: prev_offset,
        per_page: prev_limit,
        window: "before"
      )
    else
      ""
    end

    {
      next_url: next_url,
      prev_url: prev_url,
      has_more_after: has_more_after,
      has_more_before: has_more_before,
      total_count: total,
      offset: offset,
      returned: returned
    }
  end

  def creators_page_url(page, filter = nil, per_page: nil)
    browse_page_url(:creators_path, page, filter: filter, per_page: per_page)
  end

  def collections_page_url(page, filter = nil, per_page: nil)
    browse_page_url(:collections_path, page, filter: filter, per_page: per_page)
  end
end
