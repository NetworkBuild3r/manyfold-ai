# frozen_string_literal: true

# Single source of truth for models library browse: column count + page size.
# Page size is always a multiple of columns so infinite-scroll batches fill complete rows.
module BrowseGrid
  ROWS_PER_FETCH = 6
  MIN_COLUMNS = 2
  MAX_COLUMNS = 4

  module_function

  def columns(settings)
    settings = settings.with_indifferent_access if settings.respond_to?(:with_indifferent_access)
    settings.fetch("grid_columns", 3).to_i.clamp(MIN_COLUMNS, MAX_COLUMNS)
  end

  # Round preferred per_page up to the next full set of rows.
  def aligned_page_size(preferred, column_count = nil)
    cols = (column_count || MIN_COLUMNS).to_i.clamp(MIN_COLUMNS, MAX_COLUMNS)
    preferred = preferred.to_i
    preferred = fetch_page_size(cols) if preferred < cols
    ((preferred + cols - 1) / cols) * cols
  end

  def fetch_page_size(column_count)
    cols = column_count.to_i.clamp(MIN_COLUMNS, MAX_COLUMNS)
    ROWS_PER_FETCH * cols
  end

  def page_size_for_settings(settings)
    settings = settings.with_indifferent_access if settings.respond_to?(:with_indifferent_access)
    cols = columns(settings)
    preferred = settings.fetch("per_page", fetch_page_size(cols))
    aligned_page_size(preferred, cols)
  end
end
