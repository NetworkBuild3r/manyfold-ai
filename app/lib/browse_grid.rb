# frozen_string_literal: true

# Card-sized browse: layout is CSS auto-fill (fixed card min/max).
# HTML first page uses PAGE_SIZE. Stream uses offset + limit for a sliding row window.
module BrowseGrid
  PAGE_SIZE = 48
  MIN_PAGE_SIZE = 1
  MAX_PAGE_SIZE = 96

  module_function

  def page_size(_settings = nil)
    PAGE_SIZE
  end

  def page_size_for_settings(_settings = nil)
    PAGE_SIZE
  end

  # Honor client-requested page size on infinite-scroll / turbo-stream fetches.
  def page_size_for_request(params, stream:)
    if stream && (params[:per_page].present? || params[:offset].present?)
      return clamp_page_size(params[:per_page].presence || PAGE_SIZE)
    end

    PAGE_SIZE
  end

  def clamp_page_size(value)
    value.to_i.clamp(MIN_PAGE_SIZE, MAX_PAGE_SIZE)
  end

  def offset_for_request(params)
    params[:offset].to_i.clamp(0, 1_000_000)
  end
end
