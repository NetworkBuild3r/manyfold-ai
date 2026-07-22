# frozen_string_literal: true

# Card-sized browse: layout is CSS auto-fill (fixed card min/max), not column count.
# Page size is a fixed batch so every viewport width gets enough cards per fetch.
module BrowseGrid
  PAGE_SIZE = 48

  module_function

  def page_size(_settings = nil)
    PAGE_SIZE
  end

  # Settings (including legacy grid_columns / per_page) do not control layout or batch size.
  def page_size_for_settings(_settings = nil)
    PAGE_SIZE
  end
end
