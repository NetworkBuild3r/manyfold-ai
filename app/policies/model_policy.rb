class ModelPolicy < ApplicationPolicy
  def show?
    super && !(user&.sensitive_content_handling == "hide" && record.sensitive)
  end

  def gallery?
    show?
  end

  def filter_facets?
    true
  end

  def toggle_favorite?
    show?
  end

  def toggle_queue?
    show?
  end

  def configure_merge?
    merge?
  end

  def merge?
    all_of(
      update?,
      none_of(
        SiteSettings.demo_mode_enabled?
      )
    )
  end

  def unmerge?
    merge?
  end

  def upload?
    edit? && UploadPolicy.new(user, record).create?
  end

  def download?
    check_permissions(record, ["view", "edit", "own"], user)
  end

  def destroy?
    super
  end

  def scan?
    user&.is_contributor?
  end

  def sync?
    update?
  end

  def organize?
    edit?
  end

  def bulk_edit?
    user&.is_moderator?
  end

  def bulk_update?
    user&.is_moderator?
  end

  class Scope < ApplicationPolicy::Scope
    def resolve
      if user&.sensitive_content_handling == "hide"
        super.where(sensitive: false)
      else
        super
      end
    end
  end
end
