class Problem < ApplicationRecord
  include PublicIDable

  belongs_to :problematic, polymorphic: true

  validates :category, uniqueness: {scope: :problematic}, presence: true

  STATES = [
    :detected,
    :resolving,
    :resolved
  ]
  enum :state, STATES, default: :detected

  default_scope { where(ignored: false, state: [:detected, :resolving]) }
  scope :including_ignored, -> { unscope(where: :ignored) }
  scope :including_resolved, -> { unscope(where: :state) }

  scope :visible, ->(settings) {
    enabled = DEFAULT_SEVERITIES.merge(settings.symbolize_keys).select { |cat, sev| sev.to_sym != :silent }
    where(category: enabled.keys)
  }

  CATEGORIES = [
    :missing,
    :empty,
    :destination_exists, # No longer used, but kept for compatibility
    :nesting,
    :inefficient,
    :duplicate,
    :no_image,
    :no_3d_model,
    :non_manifold,
    :inside_out,
    :no_license,
    :no_links,
    :no_creator,
    :no_tags,
    :http_error,
    :file_naming
  ]
  enum :category, CATEGORIES

  SEVERITIES = [
    :silent,
    :info,
    :warning,
    :danger
  ]

  DEFAULT_SEVERITIES = ActiveSupport::HashWithIndifferentAccess.new(
    missing: :danger,
    empty: :info,
    nesting: :warning,
    inefficient: :info,
    duplicate: :warning,
    no_image: :silent,
    no_3d_model: :silent,
    non_manifold: :warning,
    inside_out: :warning,
    no_license: :silent,
    no_links: :silent,
    no_creator: :silent,
    no_tags: :silent,
    http_error: :info,
    file_naming: :warning
  )

  ICONS = ActiveSupport::HashWithIndifferentAccess.new(
    missing: "question-mark-circle",
    nesting: "files-alt",
    duplicate: "files",
    inefficient: "file-earmark-zip",
    no_image: "file-earmark-image",
    no_creator: "person-x",
    no_tags: "label",
    http_error: "question-mark-circle",
    file_naming: "folder-cross"
  )

  # Sole creation path for Problem records. All detection/creation must go through this method
  # so the unique index on [category, problematic_id, problematic_type] is respected and
  # duplicates are avoided. On concurrent insert, RecordNotUnique is rescued and we retry.
  def self.create_or_clear(problematic, category, should_exist, options = {})
    relation = Problem.unscoped.where(problematic: problematic, category: category)
    if should_exist
      problem = relation.first_or_initialize
      problem.assign_attributes(options)
      problem.ignored = false
      # If the user is actively resolving a problem, don't clobber that state from background checks.
      unless problem.resolving?
        problem.state = :detected
        problem.in_progress = false
      end
      problem.save!
    else
      relation.destroy_all
    end
    should_exist
  rescue ActiveRecord::RecordNotUnique
    relation = Problem.unscoped.where(problematic: problematic, category: category)
    problem = relation.first
    return should_exist unless problem

    problem.assign_attributes(options)
    problem.ignored = false
    unless problem.resolving?
      problem.state = :detected
      problem.in_progress = false
    end
    problem.save!
    should_exist
  end

  def parent
    if problematic_type == "ModelFile"
      problematic.model
    elsif problematic_type == "Link"
      problematic.linkable
    end
  end

  def icon
    ICONS[category] || "fire"
  end

  RESOLUTIONS = {
    missing: :destroy,
    empty: :destroy,
    nesting: :merge,
    inefficient: :convert,
    duplicate: :destroy,
    no_image: :upload,
    no_3d_model: :upload,
    non_manifold: :show,
    inside_out: :show,
    no_license: :edit,
    no_links: :edit,
    no_creator: :edit,
    no_tags: :edit,
    http_error: :edit,
    file_naming: :organize
  }

  def resolution_strategy
    RESOLUTIONS[category.to_sym] or raise NotImplementedError.new(category)
  end

  # Resolves multiple problems in one transaction. Returns a result hash for the controller.
  # When override_action is set (e.g. :ignore), that action is used for every problem.
  # { removed_ids: [...], ignored_ids: [...], redirect: url_or_nil, errors: [...] }
  def self.resolve_batch(problems, override_action: nil)
    removed_ids = []
    ignored_ids = []
    redirect_url = nil
    errors = []

    Current.set(skip_problem_checks: true) do
      ActiveRecord::Base.transaction do
        Array(problems).each do |problem|
          problem_id = problem.id
          strategy = override_action || problem.resolution_strategy
          result = if Problems::Registry.registered?(problem.category, problem.problematic_type)
            klass = Problems::Registry.for(problem.category, problem.problematic_type)
            klass.new.resolve!(problem, action: strategy)
          else
            Problems::LegacyResolver.resolve(problem, action: strategy)
          end
          removed_ids << problem_id if result[:removed]
          ignored_ids << problem_id if result[:ignored]
          redirect_url ||= result[:redirect]
        end
      end
    end

    { removed_ids: removed_ids, ignored_ids: ignored_ids, redirect: redirect_url, errors: errors }
  end
end
