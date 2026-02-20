module ModelListable
  extend ActiveSupport::Concern

  MAX_RESTORE_PAGES = 50

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

    # Restore mode only applies to HTML full-page requests (back-button scroll restoration).
    # API requests always get a standard paginated relation.
    if request.format.html? && !turbo_frame_request? && page.to_i > 1
      restore_page = [page.to_i, MAX_RESTORE_PAGES].min
      @models = @models.page(1).per(per_page * restore_page)
      @models = @models.includes [:creator, :collection]
      @models = @models.preload [:model_files, :preview_file]
      @models = ModelListRestoreWrapper.new(@models, restore_page: restore_page, per_page: per_page)
    else
      @models = @models.page(page).per(per_page)
      @models = @models.includes [:creator, :collection]
      @models = @models.preload [:model_files, :preview_file]
    end
  end
end
