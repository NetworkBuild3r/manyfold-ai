# frozen_string_literal: true

class Components::ActorCard < Components::ModelCard
  def initialize(actor:)
    @actor = actor
  end

  def before_template
  end

  def view_template
    div(class: "tw:mb-4 tw:flex tw:flex-col tw:rounded-xl tw:overflow-hidden tw:bg-white tw:dark:bg-secondary-800 tw:shadow-sm tw:hover:shadow-md tw:transition-shadow tw:relative") do
      div(class: "tw:absolute tw:top-0 tw:left-0 tw:right-0 tw:z-10 tw:px-2 tw:py-1 tw:bg-secondary-200/90 tw:dark:bg-secondary-700/90 tw:text-sm") do
        server_indicator @actor, full_address: true
      end
      PreviewFrame(object: @actor)
      div(class: "tw:p-3 tw:flex tw:flex-col tw:gap-1") { info_row }
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

  def title
    div(class: "tw:font-medium tw:text-secondary-900 tw:dark:text-secondary-100") do
      icon = f3di_icon_for(@actor.extensions&.dig("f3di:concreteType"))
      icon ? Icon(icon: icon) : span { "⁂" }
      whitespace
      span { sanitize(@actor.name) }
    end
  end

  def actions
    div(class: "tw:px-3 tw:py-2 tw:border-t tw:border-secondary-200 tw:dark:border-secondary-600") do
      div(class: "tw:flex tw:flex-wrap tw:items-center tw:gap-2") do
        div(class: "tw:min-w-0 tw:flex-1") do
          FollowButton(follower: current_user, target: @actor)
          if !@actor.local? && @actor.extensions&.dig("f3di:concreteType").nil?
            span(class: "tw:text-warning tw:ml-2") do
              Icon(icon: "exclamation-triangle-fill", label: translate("components.actor_card.non_manyfold_account"))
              t("components.actor_card.non_manyfold_account")
            end
          end
        end
        div(class: "tw:flex-shrink-0") do
          open_button
        end
      end
    end
  end
end
