# frozen_string_literal: true

# INIT-027/SPEC-003 — ActorCard uses local title_row + GoButton open (not ModelCard#info_row).
class Components::ActorCard < Components::ModelCard
  def initialize(actor:)
    @actor = actor
  end

  def before_template
  end

  def view_template
    div(class: "mb-4 flex flex-col rounded-xl overflow-hidden bg-surface dark:bg-surface-dark shadow-sm hover:shadow-md transition-shadow relative") do
      div(class: "absolute top-0 left-0 right-0 z-10 px-2 py-1 bg-secondary-200/90 dark:bg-secondary-700/90 text-sm") do
        server_indicator @actor, full_address: true
      end
      PreviewFrame(object: @actor)
      div(class: "p-3 flex flex-col gap-1") { title_row }
      actions
    end
  end

  private

  def f3di_icon_for(concrete_type)
    case concrete_type
    when "Creator"
      "person"
    when "Collection"
      "collection"
    when "Model"
      "box"
    end
  end

  def title_row
    div(class: "font-medium text-secondary-900 dark:text-secondary-100") do
      icon = f3di_icon_for(@actor.extensions&.dig("f3di:concreteType"))
      icon ? Icon(icon: icon) : span { "⁂" }
      whitespace
      span { sanitize(@actor.name) }
    end
  end

  def open_button
    GoButton(
      href: @actor.profile_url,
      label: t("components.model_card.open_button.text"),
      variant: :primary,
      icon: "box-arrow-up-right",
      aria_label: translate("components.model_card.open_button.label", name: @actor.name),
      data: {turbo_frame: "_top"}
    )
  end

  def actions
    div(class: "px-3 py-2 border-t border-secondary-200 dark:border-secondary-600") do
      div(class: "flex flex-wrap items-center gap-2") do
        div(class: "min-w-0 flex-1") do
          FollowButton(follower: current_user, target: @actor)
          if !@actor.local? && @actor.extensions&.dig("f3di:concreteType").nil?
            span(class: "text-warning ml-2") do
              Icon(icon: "exclamation-triangle-fill", label: translate("components.actor_card.non_manyfold_account"))
              t("components.actor_card.non_manyfold_account")
            end
          end
        end
        div(class: "flex-shrink-0") do
          open_button
        end
      end
    end
  end
end
