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
    @models = @models.includes [:creator, :collection]
    # preview_file only — avoid preloading every model_file on index
    @models = @models.preload [:preview_file]
  end
end
