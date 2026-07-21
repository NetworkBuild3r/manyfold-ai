class Search::FilterService
  attr_reader :collection
  attr_reader :creator
  attr_reader :owner

  # Get list filters from URL. Optional +user+ enables personal list filters (favorite/printed).
  # +default_has_image+: when true (models library), omit → with-images; has_image=0 keeps "show all".
  def initialize(params, user: nil, default_has_image: false)
    @user = user
    params = ActionController::Parameters.new(params) if params.is_a?(Hash)
    has_image_specified = param_key?(params, :has_image)
    @filters = params.permit(
      :library,
      :collection,
      :q,
      :creator,
      :link,
      :missingtag,
      :owner,
      :has_image,
      :list,
      tag: []
    )
    # Sidebar form uses "all" for unconstrained selects; drop so they do not stick as filters.
    %i[library collection creator].each do |key|
      @filters.delete(key) if @filters[key].to_s == "all"
    end
    @filters.delete(:link) if @filters[:link].blank?
    @filters.delete(:q) if @filters[:q].blank?
    normalize_has_image!(has_image_specified: has_image_specified, default_has_image: default_has_image)
    @filters.delete(:list) unless %w[favorite printed queue unprinted].include?(@filters[:list].to_s)

    @collection = Collection.find_param(parameter(:collection)) if parameter(:collection).present?
    @creator = Creator.find_param(parameter(:creator)) if parameter(:creator).present?
    @owner = User.find_param(parameter(:owner)) if parameter(:owner).present?
  end

  def any?
    !@filters.empty?
  end

  def filtering_by?(key)
    parameter(key).present?
  end

  def parameter(key)
    @filters[key]
  end

  def to_params(except: nil)
    @filters.except(except)
  end

  def models(scope)
    scope = scope.all
    scope = filter_by_owner(scope)
    scope = filter_by_library(scope)
    scope = filter_by_missing_tag(scope)
    scope = filter_by_tag(scope)
    scope = filter_by_collection(scope)
    scope = filter_by_creator(scope)
    scope = filter_by_url(scope)
    scope = filter_by_has_image(scope)
    scope = filter_by_list(scope)
    filter_by_search(scope)
  end

  def collections(scope)
    scope = scope.includes(:creator)
    scope = filter_by_owner(scope)
    scope = filter_by_collection(scope)
    scope = filter_by_creator(scope)
    filter_by_search(scope)
  end

  def creators(creator_scope, models)
    creator_scope = creator_scope.where(id: models.pluck(:creator_id).uniq)
    # Apply second-pass owner filter
    filter_by_owner(creator_scope)
  end

  def tags
    ActsAsTaggableOn::Tag.named_any(parameter(:tag)) if filtering_by?(:tag)
  end

  private

  # Filter by library
  def filter_by_library(scope)
    filtering_by?(:library) ? scope.where(library: Library.find_param(parameter(:library))) : scope
  end

  # Filter by collection
  def filter_by_collection(scope)
    case parameter(:collection)
    when nil
      scope # No collection, move along
    when ""
      scope.where(collection_id: nil)
    else
      scope.where(collection: Collection.tree_down(@collection.id))
    end
  end

  # Filter by creator
  def filter_by_creator(scope)
    case parameter(:creator)
    when nil
      scope # No creator specified, nothing to do
    when ""
      scope.where(creator_id: nil)
    else
      scope.where(creator: creator)
    end
  end

  def filter_by_owner(scope)
    owner ? scope.granted_to("own", owner).local : scope
  end

  # Filter by tag
  def filter_by_tag(scope)
    case parameter(:tag)
    when nil
      scope # No tags, move along
    when [""]
      scope.where("(select count(*) from taggings where taggings.taggable_id=models.id and taggings.context='tags')<1")
    else
      # Build query directly rather than using tagged_with, which parses the tag list again using default separators
      ::ActsAsTaggableOn::Taggable::TaggedWithQuery.build(scope, ActsAsTaggableOn::Tag, ActsAsTaggableOn::Tagging, parameter(:tag), {})
    end
  end

  # Filter by url
  def filter_by_url(scope)
    case parameter(:link)
    when nil
      scope # no filter
    when ""
      scope.where("(select count(*) from links where linkable_id=models.id and linkable_type='Model')<1")
    else
      scope.where("(select count(*) from links where linkable_id=models.id and linkable_type='Model' and url like ?)>0", "%#{parameter(:link)}%")
    end
  end

  # Filter by search query
  def filter_by_search(scope)
    if parameter(:q)
      Search::ModelSearchService.new(scope).search(parameter(:q))
    else
      scope
    end
  end

  def filter_by_missing_tag(scope)
    # Missing tags (If specific tag is not specified, require library to be set)
    if filtering_by?(:missingtag) || (filtering_by?(:missingtag) && parameter(:library))
      tag_regex_build = []
      regexes = ((parameter(:missingtag) != "") ? [parameter(:missingtag)] : Library.find_param(parameter(:library)).tag_regex)
      # Regexp match syntax - postgres is different from MySQL and SQLite
      regact = DatabaseDetector.is_postgres? ? "~" : "REGEXP"
      regexes.each do |reg|
        qreg = ActiveRecord::Base.with_connection { |conn| conn.quote(reg) }
        tag_regex_build.push "(select count(*) from tags join taggings on tags.id=taggings.tag_id where tags.name #{regact} #{qreg} and taggings.taggable_id=models.id and taggings.taggable_type='Model')<1"
      end
      qreg = ActiveRecord::Base.with_connection { |conn| conn.quote(parameter(:missingtag)) }
      tag_regex_build.push "(select count(*) from tags join taggings on tags.id=taggings.tag_id where tags.name #{regact} #{qreg} and taggings.taggable_id=models.id and taggings.taggable_type='Model')<1"
      scope.where("(" + tag_regex_build.join(" OR ") + ")")
    else
      scope
    end
  end

  # Only models whose preview_file is an image (jpg/png/…).
  # Matches grid cards: PreviewFrame lite only paints a photo for image previews.
  def filter_by_has_image(scope)
    return scope unless truthy?(parameter(:has_image))

    exts = SupportedMimeTypes.image_extensions.map(&:downcase).uniq
    return scope.none if exts.empty?

    image_filename_sql = exts.map { |ext|
      "LOWER(model_files.filename) LIKE #{ActiveRecord::Base.connection.quote("%.#{ext}")}"
    }.join(" OR ")

    scope.where(
      preview_file_id: ModelFile.without_special.where(image_filename_sql).select(:id)
    )
  end

  # Personal lists: favorites, print queue, printed, or never printed.
  def filter_by_list(scope)
    return scope if @user.blank? || !filtering_by?(:list)

    case parameter(:list).to_s
    when "favorite"
      scope.where(id: @user.favorited_model_ids.to_a)
    when "queue"
      scope.where(id: @user.queued_model_ids.to_a)
    when "printed"
      scope.where(id: @user.printed_model_ids.to_a)
    when "unprinted"
      printed = @user.printed_model_ids
      printed.empty? ? scope : scope.where.not(id: printed.to_a)
    else
      scope
    end
  end

  def truthy?(value)
    ActiveModel::Type::Boolean.new.cast(value)
  rescue ArgumentError
    %w[1 true yes on].include?(value.to_s.downcase)
  end

  def param_key?(params, key)
    params.key?(key) || params.key?(key.to_s)
  end

  # Keep explicit "0" so library default (images on) does not re-apply after the user opts out.
  def normalize_has_image!(has_image_specified:, default_has_image:)
    raw = @filters[:has_image]
    raw = raw.last if raw.is_a?(Array)

    if !has_image_specified && default_has_image
      @filters[:has_image] = "1"
    elsif has_image_specified
      @filters[:has_image] = truthy?(raw) ? "1" : "0"
    else
      @filters.delete(:has_image)
    end
  end
end
