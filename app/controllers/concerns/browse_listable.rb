# frozen_string_literal: true

# Thin pagination prep for BrowseGrid indexes (creators / collections).
module BrowseListable
  extend ActiveSupport::Concern

  included do
    include BrowseWindowable
  end

  private

  def prepare_browse_page(scope)
    prepare_browse_window(scope)
  end
end
