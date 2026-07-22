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

    stream = infinite_scroll_or_stream_request?
    per_page = BrowseGrid.page_size_for_request(params, stream: stream)
    @browse_per_page = per_page

    if stream && params[:offset].present?
      offset = BrowseGrid.offset_for_request(params)
      @browse_offset = offset
      total = @models.count
      @browse_total_count = total
      @models = @models.offset(offset).limit(per_page)
      @models = @models.includes([:creator, :collection, :tags]).preload([:preview_file])
      records = @models.load
      @browse_returned_count = records.size
      @browse_has_more_after = (offset + records.size) < total
      @browse_has_more_before = offset.positive?
      @browse_window = params[:window].presence_in(%w[before after]) || "after"
    else
      page = if stream
        params[:page].presence || 1
      else
        1
      end
      @models = @models.page(page).per(per_page)
      @models = @models.includes([:creator, :collection, :tags]).preload([:preview_file])
      @browse_offset = (page.to_i - 1) * per_page
      @browse_total_count = @models.total_count
      @browse_returned_count = @models.size
      @browse_has_more_after = @models.next_page.present?
      @browse_has_more_before = page.to_i > 1
      @browse_window = "after"
    end
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
