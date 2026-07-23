# frozen_string_literal: true

# Apply Caber permission presets and ownership after create/update.
# Extracted from CaberObject after_commit operation callbacks.
class Permissions::ApplyPreset
  def self.call(record, permission_preset: nil, owner: nil)
    new(record).call(permission_preset: permission_preset, owner: owner)
  end

  def initialize(record)
    @record = record
  end

  def call(permission_preset: nil, owner: nil)
    preset = permission_preset.nil? ? @record.instance_variable_get(:@permission_preset) : permission_preset
    apply_preset!(preset) if preset.present?
    ensure_owner!(owner)
    @record.instance_variable_set(:@permission_preset, nil)
    @record
  end

  private

  def apply_preset!(preset)
    case preset.to_sym
    when :public
      @record.grant_permission_to("view", nil)
      @record.revoke_permission("view", Role.find_or_create_by(name: "member"))
    when :member
      @record.revoke_all_permissions(nil)
      @record.grant_permission_to("view", Role.find_or_create_by(name: "member"))
    when :private
      Caber::Relation.where(object: @record, permission: ["preview", "view", "edit"]).destroy_all # rubocop:disable Pundit/UsePolicyScope
    end
  end

  def ensure_owner!(owner)
    return unless @record.permitted_users.with_permission("own").empty?

    o = owner || @record.instance_variable_get(:@owner) || SiteSettings.default_user
    @record.grant_permission_to("own", o) if o
  end
end
