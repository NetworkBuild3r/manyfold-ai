class Model < ApplicationRecord
  extend Memoist
  include PathBuilder
  include Followable
  include CaberObject
  include Linkable
  include Sluggable
  include PublicIDable
  include Commentable
  include Problematic
  include Indexable
  include FaspClient::DataSharing::Lifecycle

  broadcasts_refreshes

  # Transient flag to suppress expensive callback cascades (e.g. during bulk deletes).
  attr_accessor :skip_problem_check

  acts_as_federails_actor(
    username_field: :public_id,
    name_field: :name,
    profile_url_method: :url_for,
    # We use the Service actor type purely so Mastodon doesn't ignore the actor.
    # Actual type is differentiated with f3di:concreteType == "3DModel".
    # Ideally this would be a Document: https://www.w3.org/TR/activitystreams-vocabulary/#dfn-document
    # Hopefully at some point this can change, if Mastodon starts allowing other actor types
    # See https://github.com/mastodon/mastodon/issues/22322
    actor_type: "Service"
  )
  fasp_share_lifecycle category: "account", uri_method: :fasp_uri, only_if: :public_and_indexable?

  def fasp_uri
    federails_actor&.federated_url
  end

  scope :recent, -> { order(created_at: :desc) }

  belongs_to :library
  belongs_to :creator, optional: true
  belongs_to :collection, optional: true
  belongs_to :preview_file, class_name: "ModelFile", optional: true
  has_many :model_files, dependent: :destroy
  has_many :merge_histories, foreign_key: :target_model_id, dependent: :destroy, inverse_of: :target_model
  acts_as_taggable_on :tags

  accepts_nested_attributes_for :creator

  before_validation :strip_separators_from_path, if: :path_changed?
  before_validation :publish_creator, if: :will_be_public?
  before_validation :normalize_license, if: -> { respond_to? :license }
  # In Rails 7.1 we will be able to do this instead:
  # normalizes :license, with: -> license { license.blank? ? nil : license }

  after_create_commit :post_creation_activity
  after_create :pregenerate_downloads
  before_update :move_files, if: :need_to_move_files?
  after_update_commit :post_update_activity
  after_update :pregenerate_downloads, if: :was_changed?
  after_commit :check_for_problems_later, on: :update, unless: -> { skip_problem_check || Current.skip_problem_checks || Current.scan_batch_id.present? }

  validates :name, presence: true, on: [:create, :update, :single_upload]
  validates :path, presence: true, uniqueness: {scope: :library}, on: [:create, :update]
  validate :check_for_submodels, on: :update, if: :need_to_move_files?
  validate :destination_is_vacant, on: :update, if: :need_to_move_files?
  validates :license, spdx: true, allow_nil: true, if: -> { respond_to? :license }
  validates :public_id, multimodel_uniqueness: {punctuation_sensitive: false, case_sensitive: false, check: FederailsCommon::FEDIVERSE_USERNAMES}, if: -> { respond_to? :public_id }, on: [:create, :update]

  validate :validate_publishable

  scoped_search on: [:name, :caption]
  scoped_search on: :notes, aliases: [:description], only_explicit: true
  scoped_search relation: :library, on: :name, rename: :library, only_explicit: true, default_operator: :eq
  scoped_search relation: :creator, on: :name, rename: :creator
  scoped_search relation: :collection, on: :name, rename: :collection
  scoped_search relation: :tags, on: :name, default_operator: :eq, rename: :tag
  scoped_search relation: :model_files, on: :filename, rename: :filename, only_explicit: true
  scoped_search on: :path, only_explicit: true

  def parents
    Pathname.new(path).parent.descend.filter_map do |path|
      library.models.find_by(path: path.to_s)
    end
  end
  memoize :parents

  def was_changed?
    !previous_changes.empty?
  end

  def self.common_root(*models)
    # If there are different libraries, there is no common root
    return nil unless models.map(&:library_id).uniq.one?
    # Get each path, split, and working from the front, find the common elements

    first, *remainder = models.map { |it| it.path.split(File::SEPARATOR).without(".") }
    parts = first.zip(*remainder)
    common = parts.map { |it| (it.uniq.length == 1) ? it.first : nil }
    common = common.first(common.index(nil) || 99999)
    common.empty? ? nil : File.join(common)
  end

  def disjoint?(other)
    Model.common_root(self, other).nil?
  end

  def contains?(other)
    Model.common_root(self, other) == path
  end

  def adopt_file(file, path_prefix: nil)
    new_filename = path_prefix ? File.join(path_prefix, file.filename) : file.filename
    existing_file = model_files.find_by(filename: new_filename)

    if existing_file
      if file.digest.present? && file.digest == existing_file.digest
        # Identical content at same path -- deduplicate (don't delete; let source destroy handle it)
        return {status: :deduplicated, existing_file_id: existing_file.id}
      else
        # Name collision, different content -- disambiguate
        suffix = file.digest.presence || SecureRandom.hex(6)
        new_filename = "#{File.basename(new_filename, ".*")}_#{suffix}#{File.extname(new_filename)}"
      end
    end

    file.update!(filename: new_filename, model: self)
    file.reattach!
    {status: :adopted}
  end

  def merge!(*models)
    models = models[0] if models.length == 1 && models[0].is_a?(Enumerable)

    models.each do |other|
      ActiveRecord::Base.transaction do
        path_prefix = compute_merge_prefix(other)

        moved_files = []
        other.model_files.to_a.each do |file|
          source_filename = file.filename
          result = adopt_file(file, path_prefix: path_prefix)

          moved_files << {
            id: file.id,
            source_filename: source_filename,
            merged_filename: (result[:status] == :adopted) ? file.filename : nil,
            deduplicated: result[:status] == :deduplicated,
            existing_file_id: result[:existing_file_id]
          }
        end

        MergeHistory.create!(
          target_model: self,
          source_library_id: other.library_id,
          source_path: other.path,
          source_name: other.name,
          path_prefix: path_prefix,
          source_metadata: {
            creator_id: other.creator_id,
            collection_id: other.collection_id,
            license: other.license,
            caption: other.caption,
            notes: other.notes,
            sensitive: other.sensitive,
            tag_list: other.tag_list,
            links: other.links.map(&:url),
            preview_filename: other.preview_file&.filename
          },
          moved_files: moved_files
        )

        # Merge metadata (target wins for single-value fields)
        self.creator ||= other.creator
        self.collection ||= other.collection
        self.license ||= other.license
        self.caption ||= other.caption
        self.notes ||= other.notes
        self.sensitive ||= other.sensitive
        tag_list.add(*other.tag_list)
        self.links_attributes = other.links.map { |it| {url: it.url} }
        save!

        other.reload
        other.destroy!
      end
      check_for_problems_later
    end
  end

  UNMERGE_WINDOW = 30.days

  def unmerge!(merge_history)
    history = merge_history.is_a?(MergeHistory) ? merge_history : merge_histories.find(merge_history)
    raise ArgumentError, "merge history does not belong to this model" if history.target_model_id != id
    raise ArgumentError, "merge already undone" if history.undone_at.present?
    raise ArgumentError, "merge is too old to undo" if history.created_at < UNMERGE_WINDOW.ago
    if history.source_library_id.nil?
      raise ActiveRecord::RecordNotFound,
        "Cannot unmerge: source library no longer exists (was deleted after merge)"
    end

    ActiveRecord::Base.transaction do
      Current.set(skip_problem_checks: true) do
        library = Library.find(history.source_library_id) # rubocop:disable Pundit/UsePolicyScope -- internal unmerge, not controller
        source_meta = history.source_metadata || {}

        new_path = history.source_path
        if library.models.exists?(path: new_path.trim_path_separators)
          new_path = "#{new_path.trim_path_separators}--unmerged-#{history.id}"
        end

        # Guard against creator/collection deleted between merge and unmerge
        creator = Creator.find_by(id: source_meta["creator_id"])
        collection = Collection.find_by(id: source_meta["collection_id"])

        new_model = library.models.create!(
          name: history.source_name,
          path: new_path.trim_path_separators,
          creator_id: creator&.id,
          collection_id: collection&.id,
          license: source_meta["license"],
          caption: source_meta["caption"],
          notes: source_meta["notes"],
          sensitive: source_meta["sensitive"]
        )

        new_model.tag_list = Array(source_meta["tag_list"])
        new_model.links_attributes = Array(source_meta["links"]).map { |url| {url: url} }
        new_model.save!

        Array(history.moved_files).each do |entry|
          file_id = entry["id"] || entry[:id]
          source_filename = entry["source_filename"] || entry[:source_filename]
          was_deduplicated = entry["deduplicated"] || entry[:deduplicated]

          if was_deduplicated
            existing_id = entry["existing_file_id"] || entry[:existing_file_id]
            existing_file = ModelFile.find_by(id: existing_id)
            next unless existing_file && source_filename.present?

            new_file = new_model.model_files.create!(
              filename: source_filename,
              digest: existing_file.digest,
              size: existing_file.size,
              presupported: existing_file.presupported,
              y_up: existing_file.y_up,
              previewable: existing_file.previewable
            )
            copy_file_to_model_file(existing_file, new_file)
          else
            file = ModelFile.find_by(id: file_id)
            next unless file && source_filename.present?

            file.filename = source_filename
            new_model.adopt_file(file)
          end
        end

        if (preview_filename = history.source_preview_filename)
          preview = new_model.model_files.find_by(filename: preview_filename)
          new_model.update!(preview_file: preview) if preview
        end

        history.update!(undone_at: Time.current)
        new_model
      end
    end
  end

  def create_or_update_file_from_url(url:, filename:)
    uri = URI.parse(url)
    file = model_files.find_or_create_by(filename: filename)
    file.update_from_url!(url: uri.to_s)
    file
  rescue URI::InvalidURIError
  end

  def delete_from_disk_and_destroy
    self.skip_problem_check = true

    Current.set(skip_problem_checks: true) do
      # Remove all presupported_version relationships first, they get in the way
      # This will go away later when we do proper file relationships rather than linking the tables directly
      model_files.update_all(presupported_version_id: nil) # rubocop:disable Rails/SkipsModelValidations
      # Trigger deletion for each file separately, to make sure cleanup happens
      model_files.each { |f| f.delete_from_disk_and_destroy }
      # Remove tags first - sometimes this causes problems if we don't do it beforehand
      update!(tags: [])
      # Delete directory corresponding to model
      library.storage.delete_prefixed(path)
      # Remove from DB
      destroy
    end
  end

  def contained_models
    previous_library.models.where(
      Model.arel_table[:path].matches(
        Model.sanitize_sql_like(previous_path) + "/%",
        "\\"
      )
    )
  end

  def contains_other_models?
    contained_models.exists?
  end

  def needs_organizing?
    formatted_path != path
  end

  def new?
    tags.where(name: SiteSettings.model_tags_auto_tag_new).any?
  end

  def valid_preview_files
    model_files.select { |it| it.is_image? || it.is_renderable? }
  end

  def image_files
    model_files.select(&:is_image?)
  end

  def three_d_files
    model_files.select(&:is_3d_model?)
  end

  def exists_on_storage?
    library.has_folder?(path)
  end

  def organize!
    autoupdate_path
    save!
  end

  def self.create_from(other, link_preview_file: false, name: nil, path: nil)
    new_model = other.dup
    new_model.update(
      path: path,
      name: name || "Copy of #{other.name}",
      public_id: nil,
      tags: other.tags,
      preview_file: link_preview_file ? other.preview_file : nil
    )
    path ? new_model.save! : new_model.organize!
    # Wipe permissions and copy from old model
    new_model.caber_relations.delete_all
    new_model.update!(
      caber_relations_attributes: other.caber_relations.all.map { |it| {permission: it.permission, subject: it.subject} }
    )
    new_model
  end

  def split!(files: [])
    preview_file_will_move = files.include?(preview_file)
    new_model = nil
    ActiveRecord::Base.transaction do
      new_model = Model.create_from(self, link_preview_file: preview_file_will_move)
      # Clear preview file if it was moved
      update!(preview_file: nil) if preview_file_will_move
      # Move files
      files.each { |it| new_model.adopt_file(it) }
    end
    new_model
  end

  def has_supported_and_unsupported?
    model_files.exists?(presupported: true) &&
      model_files.exists?(presupported: false)
  end

  def file_extensions
    model_files.map(&:extension).uniq
  end

  def size_on_disk
    model_files.pluck(:size).compact.sum
  end

  def to_activitypub_object
    ActivityPub::ModelSerializer.new(self).serialize
  end

  def add_new_files_later(include_all_subfolders: false, delay: 0.seconds, scan_batch_id: nil)
    Scan::Model::AddNewFilesJob.set(wait: delay).perform_later(
      id,
      include_all_subfolders: include_all_subfolders,
      scan_batch_id: scan_batch_id
    )
  end

  # Scan batch ID is only in job arguments and Current (ActiveSupport::CurrentAttributes).
  # It is not stored on the model; it is used for cache-key idempotency in FinalizeScanBatchJob.
  SCAN_STALE_THRESHOLD = 10.minutes

  def scan_stale?
    scan_started_at.present? && scan_started_at < SCAN_STALE_THRESHOLD.ago
  end

  def check_later(delay: 0.seconds, scan_batch_id: nil)
    scan_batch_id ||= SecureRandom.uuid
    if has_attribute?(:scan_started_at)
      update_column(:scan_started_at, Time.current) # rubocop:disable Rails/SkipsModelValidations
    end
    Scan::CheckModelJob.set(wait: delay).perform_later(id, scan_batch_id: scan_batch_id)
  end

  def check_for_problems_later(delay: 5.seconds)
    return if skip_problem_check || Current.skip_problem_checks

    # Debounce: avoid enqueuing multiple identical checks in quick succession.
    begin
      key = "manyfold:problems:debounce:model:#{id}"
      wrote = Rails.cache.write(key, true, expires_in: delay + 30.seconds, unless_exist: true)
      return unless wrote
    rescue ArgumentError, NoMethodError
      # Cache store doesn't support `unless_exist`; fall back to job uniqueness.
    end

    Scan::Model::CheckForProblemsJob.set(wait: delay).perform_later(id)
  end

  def organize_later(delay: 5.seconds)
    OrganizeModelJob.set(wait: delay).perform_later(id)
  end

  def parse_metadata_later(delay: 0.seconds, scan_batch_id: nil)
    Scan::Model::ParseMetadataJob.set(wait: delay).perform_later(id, scan_batch_id: scan_batch_id)
  end

  def pregenerate_downloads(delay: 10.minutes, queue: nil)
    # By default, give 10 minutes' grace for followup changes before we pregenerate the download
    # Other scan jobs could be running, which might take some time.
    # This is brittle, and we need a better way to say "this model is done changing for a while"
    return unless SiteSettings.pregenerate_downloads

    download_types = [nil]
    download_types += ["supported", "unsupported"] if has_supported_and_unsupported?
    download_types += file_extensions.excluding("json")
    download_types.each do |selection|
      ArchiveDownloadService.new(model: self, selection: selection).prepare(delay: delay, queue: queue)
    end
  end

  private

  def compute_merge_prefix(other)
    if contains?(other)
      Pathname.new(other.path).relative_path_from(Pathname.new(path)).to_s
    elsif other.library_id == library_id && Model.common_root(self, other)
      Pathname.new(other.path).relative_path_from(Pathname.new(path)).to_s
    else
      File.basename(other.path)
    end
  end

  # Copy physical file from source_file (e.g. target's file) to dest_file (e.g. restored model's new record).
  def copy_file_to_model_file(source_file, dest_file)
    dest_path = dest_file.path_within_library
    dest_storage = dest_file.model.library.storage
    source_file.attachment.download do |io|
      dest_storage.upload(io, dest_path)
    end
    dest_file.attach_existing_file!
  end

  def normalize_license
    self.license = nil if license.blank?
  end

  def strip_separators_from_path
    self.path = path&.trim_path_separators
  end

  def previous_library
    library_id_changed? ? Library.find_by(id: library_id_was) : library
  end

  def previous_path
    path_changed? ? path_was : path
  end

  def need_to_move_files?
    library_id_changed? ||
      (path_changed? &&
        (previous_path.trim_path_separators != path.trim_path_separators)
      )
  end

  def autoupdate_path
    self.path = formatted_path
  end

  def check_for_submodels
    if contains_other_models?
      errors.add(library_id_changed? ? :library : :path, :nested)
    end
  end

  def destination_is_vacant
    if exists_on_storage? && need_to_move_files?
      errors.add(:path, :destination_exists)
    end
  end

  def move_files
    # Move all the files
    model_files.each(&:reattach!)
    # Remove the old folder if it's still there
    previous_library.storage.delete_prefixed(previous_path)
  end

  def post_creation_activity
    Activity::ModelPublishedJob.set(wait: 5.seconds).perform_later(id) if public?
  end

  def post_update_activity
    if creator_previously_changed? && creator&.public?
      Activity::ModelPublishedJob.set(wait: 5.seconds).perform_later(id)
    elsif collection_previously_changed? && collection&.public?
      Activity::ModelCollectedJob.set(wait: 5.seconds).perform_later(id, collection.id)
    elsif just_became_public?
      Activity::ModelPublishedJob.set(wait: 5.seconds).perform_later(id)
    elsif public? && noteworthy_change?
      Activity::ModelUpdatedJob.set(wait: 5.seconds).perform_later(id)
    end
  end

  def noteworthy_change?
    # Exclude internal fields, they're not interesting enough to post comments for
    !previous_changes.keys.without([
      "id",
      "path",
      "library_id",
      "created_at",
      "updated_at",
      "preview_file_id",
      "slug",
      "public_id",
      "name_lower"
    ]).empty?
  end

  def validate_publishable
    # If the model will be public
    return unless will_be_public?
    # Check required fields
    errors.add :license, :blank if license.nil?
    errors.add :creator, :blank if creator.nil?
    errors.add :creator, :private if creator && !creator.public?
  end

  def publish_creator
    creator&.update!(caber_relations_attributes: [{permission: "view", subject: nil}]) unless creator&.public?
  end
end
