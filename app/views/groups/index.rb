# frozen_string_literal: true

class Views::Groups::Index < Views::Base
  def initialize(creator:, groups:)
    @creator = creator
    @groups = groups
  end

  def view_template
    PageTitle title: t("views.groups.index.title"), breadcrumbs: {
      Creator.model_name.human(count: 100) => creators_path,
      @creator.name => creator_path(@creator)
    }
    p { t("views.groups.index.description") }
    table class: "tw:w-full tw:border-collapse tw:border tw:border-secondary-200 dark:tw:border-secondary-600 [&>tbody>tr:nth-child(even)]:tw:bg-secondary-50 [&>tbody>tr:nth-child(even)]:dark:tw:bg-secondary-800/50" do
      tr do
        th(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2 tw:text-left") { Group.human_attribute_name :name }
        th(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2 tw:text-left") { Group.human_attribute_name :memberships }
        th(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2 tw:text-left") { Group.human_attribute_name :invitations }
        th(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2 tw:text-left") { Group.human_attribute_name :description }
        th(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2 tw:text-left") { Group.human_attribute_name :typed_id }
        th(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2")
      end
      @groups.each do |group|
        tr do
          td(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2") { group.name }
          td(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2") { t("views.groups.index.member_count", count: group.members.active.count) }
          td(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2") { (t("views.groups.index.invite_count", count: group.members.invited.count) if group.members.invited.any?) }
          td(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2") { group.description }
          td(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2") { CopyableText text: group.typed_id, label: t("views.groups.index.copy") }
          td(class: "tw:border tw:border-secondary-200 tw:dark:tw:border-secondary-600 tw:px-4 tw:py-2") { GoButton label: t("views.groups.edit.title"), href: edit_creator_group_path(@creator, group), icon: "pencil", variant: :primary }
        end
      end
    end
    GoButton href: new_creator_group_path(@creator), label: t("views.groups.new.title"), variant: :primary
  end
end
