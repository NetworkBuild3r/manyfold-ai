module Sortable
  extend ActiveSupport::Concern

  included do
    before_action :remember_ordering
  end

  def current_ordering
    if current_user
      current_user.sort_order.to_s
    else
      session["order"].to_s
    end
  end

  def remember_ordering
    if current_user
      current_user.update!(sort_order: params["order"]) if params["order"].presence
    else
      session["order"] ||= "name"
      session["order"] = params["order"] if params["order"].presence
    end
  end

  def apply_sort_order(scope)
    case current_ordering
    when "recent"
      scope.order(created_at: :desc)
    when "updated"
      scope.order(updated_at: :desc)
    when "name"
      scope.order(name_lower: :asc)
    when "random"
      # Seeded md5 order so infinite-scroll pages are a stable continuation
      # (bare RANDOM() re-shuffles every request and duplicates cards).
      scope.in_random_order(seed: random_browse_seed)
    else
      scope
    end
  end

  private

  def infinite_scroll_or_stream_request?
    request.format.turbo_stream? || request.headers["X-Infinite-Scroll"].present?
  end

  # Stable for scroll continuation; reshuffles on models HTML load or filter change.
  def random_browse_seed
    filter_key = if defined?(@filter) && @filter.respond_to?(:to_params)
      @filter.to_params.to_query
    else
      ""
    end
    fingerprint = [controller_name, current_ordering, filter_key].join(":")

    regenerate = session[:random_order_seed].blank? ||
      session[:random_order_fingerprint] != fingerprint

    # Models HTML always starts at page 1 — new visit gets a fresh shuffle.
    # Do not reshuffle creators/collections on every classic ?page=N HTML load.
    if !infinite_scroll_or_stream_request? && current_ordering == "random"
      regenerate = true if controller_name == "models"
      regenerate = true if params["order"].presence == "random"
    end

    if regenerate
      session[:random_order_seed] = SecureRandom.hex(16)
      session[:random_order_fingerprint] = fingerprint
    end

    session[:random_order_seed]
  end
end
