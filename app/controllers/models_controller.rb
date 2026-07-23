require "fileutils"

class ModelsController < ApplicationController
  include ModelListable
  include Permittable
  include LinkableController

  rate_limit to: 10, within: 3.minutes, only: :create

  before_action :redirect_search, only: [:index], if: -> { params.key?(:q) }
  before_action :get_creators_and_collections, only: [:new, :edit, :bulk_edit]
  before_action :set_returnable, only: [:bulk_edit, :edit, :new]
  before_action :clear_returnable, only: [:bulk_update, :update, :create]
  # Filterable also registers get_filters for index/show; keep index/show here so
  # ModelsController is not dependent on include order of ModelListable.
  before_action :get_filters, only: [:bulk_edit, :bulk_update, :bulk_edit_selected, :index, :show, :filter_facets] # rubocop:todo Rails/LexicallyScopedActionFilter
  before_action :get_model, except: [:bulk_edit, :bulk_update, :bulk_edit_selected, :index, :new, :create, :filter_facets]
  before_action -> { set_indexable @model if @model }

  after_action :verify_policy_scoped, only: [:bulk_edit, :bulk_update]

  include ModelsController::Merge

  def get_filters
    @filter = Search::FilterService.new(params, user: current_user, default_has_image: true)
  end

  def index
    @models = @filter.models(policy_scope(Model))
    @search = params[:q].presence
    prepare_model_list
    set_indexable @models
    respond_to do |format|
      format.turbo_stream { render "models/page" }
      format.html { render layout: "card_list_page" }
      format.manyfold_api_v0 { render json: ManyfoldApi::V0::ModelListSerializer.new(@models).serialize }
    end
  end

  # Lazy facet options for the models filter form (Turbo Frame).
  # Keeps creator/collection/library queries off the critical TTFB path.
  def filter_facets
    authorize :model
    load_model_filter_sidebar_options
    render layout: false
  end

  def show
    respond_to do |format|
      format.html do
        files = policy_scope(@model.model_files).without_special
        @locked_files = @model.model_files.without_special.count - files.count
        @images = files.select(&:is_image?)
        @images.unshift(@model.preview_file) if @images.delete(@model.preview_file)
        if helpers.file_list_settings["hide_presupported_versions"]
          hidden_ids = files.select(:presupported_version_id).where.not(presupported_version_id: nil)
          files = files.where.not(id: hidden_ids)
        end
        files = files.includes(:presupported_version, :problems)
        files = files.reject(&:is_image?)
        @groups = helpers.group(files)
        @num_files = files.count
      end
      format.zip do
        if policy(@model).download?
          download = ArchiveDownloadService.new(model: @model, selection: params[:selection])
          if download.ready?
            send_file(download.output_file, filename: download.filename, type: :zip, disposition: :attachment)
          elsif download.preparing?
            redirect_to model_path(@model, format: :html), notice: t(".download_preparing")
          else
            download.prepare
            redirect_to model_path(@model, format: :html), notice: t(".download_requested")
          end
        else
          head :forbidden
        end
      end
      format.oembed { render json: OEmbed::ModelSerializer.new(@model, helpers.oembed_params).serialize }
      format.manyfold_api_v0 { render json: ManyfoldApi::V0::ModelSerializer.new(@model).serialize }
    end
  end

  # Lightweight image gallery for the browse lightbox (turbo-frame only).
  def gallery
    files = policy_scope(@model.model_files).without_special
    @images = files.select(&:is_image?)
    @images.unshift(@model.preview_file) if @images.delete(@model.preview_file)
    render layout: false
  end

  def new
    @model = Model.new # dummy model object
    authorize :model
    generate_available_tag_list
  end

  def edit
    @model.links.build if @model.links.empty? # populate empty link
    @model.caber_relations.build if @model.caber_relations.empty?
    generate_available_tag_list
  end

  def create
    authorize :model
    p = upload_params
    library = SiteSettings.show_libraries ? Library.find_param(p[:library]) : Library.default
    result = Model::Upload.call(library: library, params: p, owner: current_user)
    @model = result.model
    if result.valid?
      respond_to do |format|
        format.html { redirect_to models_path, notice: t(".success") }
        format.manyfold_api_v0 { head :accepted }
      end
    else
      get_creators_and_collections
      generate_available_tag_list
      respond_to do |format|
        format.html { render :new, status: :unprocessable_content }
        format.manyfold_api_v0 { render json: @model.errors.to_json, status: :unprocessable_content }
      end
    end
  end

  def update
    hash = model_params
    hash = hash.respond_to?(:to_unsafe_h) ? hash.to_unsafe_h : hash.to_h
    hash = hash.deep_stringify_keys
    result = if hash["permission_preset"].to_s == "public"
      begin
        Model::Publish.call(@model, **hash.except("permission_preset").symbolize_keys)
        true
      rescue Model::Publish::NotPublishable
        false
      end
    else
      Model::Update.call(@model, hash)
    end
    respond_to do |format|
      format.html do
        if result
          redirect_to @model, notice: t(".success")
        else
          get_creators_and_collections
          edit
          render :edit, status: :unprocessable_content
        end
      end
      format.manyfold_api_v0 do
        if result
          render json: ManyfoldApi::V0::ModelSerializer.new(@model).serialize
        else
          render json: @model.errors.to_json, status: :unprocessable_content
        end
      end
    end
  end

  def scan
    # Start the scans
    @model.check_later
    # Back to the model page
    redirect_to @model, notice: t(".success")
  end

  def toggle_favorite
    toggle_personal_list(:favorite, added_key: ".added", removed_key: ".removed")
  end

  def toggle_queue
    toggle_personal_list(:want_to_print, added_key: ".queue_added", removed_key: ".queue_removed")
  end

  def unmerge
    authorize @model, :unmerge?
    history = @model.merge_histories.active.find(params[:merge_history_id])
    new_model = @model.unmerge!(history)
    redirect_to model_path(new_model), notice: t(".success")
  rescue ActiveRecord::RecordNotFound
    redirect_back_or_to @model, alert: t(".missing")
  rescue ArgumentError => e
    redirect_back_or_to @model, alert: e.message
  end

  def bulk_edit_selected
    authorize Model, :bulk_edit?
    ids = params.permit(ids: [])[:ids].to_a.compact_blank
    if ids.any?
      session[:bulk_edit_model_ids] = policy_scope(Model, policy_scope_class: ApplicationPolicy::UpdateScope).where(public_id: ids).pluck(:public_id)
    end
    redirect_to edit_models_path, notice: (ids.any? ? t(".success", count: session[:bulk_edit_model_ids].size) : t(".no_selection"))
  end

  def bulk_edit
    authorize Model
    scope = policy_scope(Model, policy_scope_class: ApplicationPolicy::UpdateScope).includes(:collection, :creator)
    @models = if session[:bulk_edit_model_ids].present?
      scope.where(public_id: session[:bulk_edit_model_ids])
    else
      @filter.models(scope)
    end
    page = params[:page] || 1
    @models = @models.page(page).per(helpers.pagination_settings["per_page"] * 2)
    @filter_in_place = true
    generate_available_tag_list
    set_indexable @models
  end

  def bulk_update
    authorize Model
    hash = bulk_update_params
    hash[:library_id] = hash.delete(:new_library_id) if hash[:new_library_id]
    add_tags = hash.delete(:add_tags) || []
    remove_tags = hash.delete(:remove_tags) || []

    models_to_update = if params.key?(:update_all)
      if session[:bulk_edit_model_ids].present?
        ids = session[:bulk_edit_model_ids]
        session.delete(:bulk_edit_model_ids)
        policy_scope(Model, policy_scope_class: ApplicationPolicy::UpdateScope).where(public_id: ids)
      else
        @filter.models(policy_scope(Model, policy_scope_class: ApplicationPolicy::UpdateScope))
      end
    else
      session.delete(:bulk_edit_model_ids) if session[:bulk_edit_model_ids].present?
      ids = params[:models].select { |k, v| v == "1" }.keys
      policy_scope(Model, policy_scope_class: ApplicationPolicy::UpdateScope).where(public_id: ids)
    end

    Model::BulkUpdate.call(models: models_to_update, attributes: hash, add_tags: add_tags, remove_tags: remove_tags)
    redirect_back_or_to edit_models_path(@filter.to_params), notice: t(".success")
  end

  def destroy
    model_param = @model.to_param
    from_show_page = destroy_referer_is_show_page?
    @model.delete_from_disk_and_destroy
    respond_to do |format|
      format.turbo_stream do
        if from_show_page
          # Model page is gone — leave the library, don't try to remove a card.
          redirect_to models_path, status: :see_other, notice: t(".success")
        else
          render turbo_stream: turbo_stream.remove(Components::ModelCard.dom_id_for_param(model_param))
        end
      end
      format.html do
        if from_show_page
          redirect_to root_path, notice: t(".success")
        else
          redirect_back_or_to root_path, notice: t(".success")
        end
      end
      format.manyfold_api_v0 { head :no_content }
    end
  end

  private

  def redirect_search
    redirect_to new_follow_path(uri: params[:q]) if params[:q]&.match?(/(@|acct:)?([a-z0-9\-_.]+)@(.*)/)
    if params[:q]&.match?(URI::RFC2396_PARSER.make_regexp)
      if (link = Link.find_by(url: params[:q]))
        redirect_to link.linkable
      elsif Link.deserializer_for(url: params[:q])
        redirect_to new_import_path(url: params[:q])
      end
    end
  end

  def generate_available_tag_list
    @available_tags = policy_scope(ActsAsTaggableOn::Tag).where(
      id: policy_scope(ActsAsTaggableOn::Tagging).where(
        taggable_type: "Model", taggable_id: policy_scope(Model).select(:id)
      ).select(:tag_id)
    ).order(:name)
  end

  def bulk_update_params
    params.permit(
      :creator_id,
      :collection_id,
      :new_library_id,
      :organize,
      :license,
      :sensitive,
      add_tags: [],
      remove_tags: []
    ).compact_blank
  end

  def model_params
    if is_api_request?
      raise ActionController::BadRequest unless params[:json]
      ManyfoldApi::V0::ModelDeserializer.new(object: params[:json], user: current_user, record: @model).deserialize
    else
      Form::ModelDeserializer.new(params: params, user: current_user, record: @model).deserialize
    end
  end

  def upload_params
    if is_api_request?
      raise ActionController::BadRequest unless params[:json]
      ManyfoldApi::V0::UploadedModelDeserializer.new(object: params[:json], user: current_user).deserialize
    else
      Form::UploadedModelDeserializer.new(params: params, user: current_user).deserialize
    end
  end

  def get_model
    @model = @linkable = policy_scope(Model).find_param(params[:id])
    authorize @model
    @title = @model.name
  end

  def get_creators_and_collections
    # Creators and collections that we can assign this model to
    @creators = policy_scope(Creator, policy_scope_class: ApplicationPolicy::UpdateScope).local.order("LOWER(creators.name) ASC")
    @default_creator = @creators.first if @creators.one?
    @collections = policy_scope(Collection, policy_scope_class: ApplicationPolicy::UpdateScope).local.order("LOWER(collections.name) ASC")
  end

  def set_returnable
    session[:return_after_new] = request.fullpath.split("?")[0]
    @new_collection = Collection.find_param(params[:new_collection]) if params[:new_collection]
    @new_creator = Creator.find_param(params[:new_creator]) if params[:new_creator]
    if @model
      @model.collection = @new_collection if @new_collection
      @model.creator = @new_creator if @new_creator
    end
  end

  def clear_returnable
    session[:return_after_new] = nil
  end

  def toggle_personal_list(list_name, added_key:, removed_key:)
    authorize @model, :show?
    if current_user.blank?
      redirect_to new_user_session_path, alert: t("devise.failure.unauthenticated")
      return
    end
    if current_user.listed?(@model, list_name)
      current_user.delist(@model, list_name)
      notice = t(removed_key)
    else
      current_user.list(@model, list_name)
      notice = t(added_key)
    end
    respond_to do |format|
      format.turbo_stream { render "models/toggle_list" }
      format.html { redirect_back_or_to @model, notice: notice }
    end
  end

  def destroy_referer_is_show_page?
    return false if request.referer.blank?

    URI.parse(request.referer).path == model_path(@model)
  rescue URI::InvalidURIError
    false
  end
end
