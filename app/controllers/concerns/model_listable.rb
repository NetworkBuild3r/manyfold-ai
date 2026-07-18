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

    per_page = helpers.pagination_settings["per_page"]
    page = params[:page] || 1

    # Always serve a single page. Multi-page "restore" preloads (up to 50 pages)
    # blew browser memory on back-navigation. Infinite scroll + windowing handles
    # forward load; ?page=N lands on that page and scrolls from there.
    @models = @models.page(page).per(per_page)
    @models = @models.includes [:creator, :collection, :tags]
    # preview_file only — avoid preloading every model_file on index
    @models = @models.preload [:preview_file]

    load_model_filter_sidebar_options
  end

  # Options for the models index filter form (full HTML only — skip turbo/infinite-scroll fragments).
  def load_model_filter_sidebar_options
    return unless controller_name == "models" && action_name == "index"
    return if turbo_frame_request?
    return if request.headers["X-Infinite-Scroll"].present?
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
