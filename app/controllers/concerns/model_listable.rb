module ModelListable
  extend ActiveSupport::Concern

  included do
    include TagListable
    include Filterable
    include Sortable
  end

  private

  def prepare_model_list
    # Ordering
    @models = apply_sort_order(@models)

    @tags, @unrelated_tag_count = generate_tag_list(@models, @filter.tags)
    @tags, @kv_tags = split_key_value_tags(@tags)
    @unrelated_tag_count = nil unless @filter.any?

    # Card-sized grid: fixed batch size. CSS auto-fill owns column count.
    per_page = BrowseGrid.page_size
    @browse_per_page = per_page

    # Full HTML browse always starts at page 1 (one infinite page in the address bar).
    # Only turbo-stream / infinite-scroll fetches advance via ?page=N.
    page = if infinite_scroll_or_stream_request?
      params[:page].presence || 1
    else
      1
    end
    @models = @models.page(page).per(per_page)
    @models = @models.includes [:creator, :collection, :tags]
    # preview_file only — avoid preloading every model_file on index
    @models = @models.preload [:preview_file]

    # Filter sidebar facets load via ModelsController#filter_facets Turbo Frame —
    # not on the critical path for first byte.
  end

  # Options for the models index filter form (lazy Turbo Frame or explicit call).
  def load_model_filter_sidebar_options
    return unless controller_name == "models"
    return unless %w[index filter_facets].include?(action_name)
    return if action_name == "index" && (
      turbo_frame_request? || request.format.turbo_stream? || request.headers["X-Infinite-Scroll"].present?
    )
    return unless request.format.html?

    visible_models = policy_scope(Model)
    @filter_libraries = policy_scope(Library).order(Arel.sql("LOWER(libraries.name) ASC"))
    @filter_creators = policy_scope(Creator)
      .where(id: visible_models.where.not(creator_id: nil).select(:creator_id))
      .order(Arel.sql("LOWER(creators.name) ASC"))
      .limit(1000)
    @filter_collections = policy_scope(Collection)
      .where(id: visible_models.where.not(collection_id: nil).select(:collection_id))
      .order(Arel.sql("LOWER(collections.name) ASC"))
      .limit(1000)
  end
end
