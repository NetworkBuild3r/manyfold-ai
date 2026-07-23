module CaberObject
  extend ActiveSupport::Concern
  include Caber::Object

  included do
    can_grant_permissions_to User
    can_grant_permissions_to Role

    attr_writer :owner
    attr_writer :permission_preset
    accepts_nested_attributes_for :caber_relations, reject_if: :all_blank, allow_destroy: true

    before_validation :ensure_permission_preset_precedence

    before_create :set_default_permission_preset
    # Explicit Permissions::ApplyPreset is preferred; these callbacks cover create
    # paths that do not go through Model::Update yet.
    after_commit :apply_permissions_from_preset_safely
    after_create_commit :apply_owner_safely

    before_update -> { @was_private = !public? }
  end

  def public?
    return false unless caber_ready?
    Pundit::PolicyFinder.new(self.class).policy.new(nil, self).show?
  end

  def private?
    caber_relations.where(subject_type: "Role").or(caber_relations.where(subject: nil)).none?
  end

  def just_became_public?
    public? && @was_private
  end

  def set_default_permission_preset
    @permission_preset ||= SiteSettings.default_viewer_role
  end

  def apply_permissions_from_preset_safely
    return if @permissions_applied
    return if @permission_preset.blank?

    Permissions::ApplyPreset.call(self)
    @permissions_applied = true
  end

  def apply_owner_safely
    return if @owner_applied
    return unless permitted_users.with_permission("own").empty?

    Permissions::ApplyPreset.call(self)
    @owner_applied = true
  end

  # Legacy method names kept for callers/tests that stub them.
  alias_method :set_permissions_from_preset, :apply_permissions_from_preset_safely
  alias_method :set_owner, :apply_owner_safely

  def will_be_public?
    return false unless caber_ready?
    @permission_preset == "public" || caber_relations.find { |it| it.subject.nil? }
  end

  # True only when transitioning to public (preset or new/changed public grant).
  # Already-public models must not re-run publishability checks on every save —
  # e.g. tag clears during delete, or metadata edits after a bulk public grant.
  def becoming_public?
    return false unless caber_ready?
    return true if @permission_preset.to_s == "public"

    caber_relations.any? { |rel| rel.subject.nil? && (rel.new_record? || rel.has_changes_to_save?) }
  end

  def matching_permission_preset
    total = caber_relations.count
    if total == 1 && caber_relations.where(permission: "own").one?
      "private"
    elsif total == 2 && caber_relations.where(permission: "view", subject: Role.find_by!(name: "member")).one?
      "member"
    elsif total == 2 && caber_relations.where(permission: "view", subject: nil).one?
      "public"
    else
      ""
    end
  end

  private

  def caber_ready?
    DatabaseDetector.table_ready? "caber_relations"
  end

  def ensure_permission_preset_precedence
    self.caber_relations_attributes = [] if @permission_preset.present?
  end
end
