# frozen_string_literal: true

class Components::StatusBadges < Components::Base
  # INIT-027/SPEC-011 — wrapper/new-badge class channel for specs.
  WRAPPER_CLASS = "status-badges"
  NEW_BADGE_CLASS = "text-warning"

  register_output_helper :problem_icon_tag
  register_value_helper :problems_including_files
  register_value_helper :problem_settings
  register_value_helper :policy

  def initialize(model:)
    @model = model
  end

  def render?
    @model.present?
  end

  def view_template
    span class: WRAPPER_CLASS do
      if @model.new?
        span class: NEW_BADGE_CLASS do
          Icon(icon: "stars", label: t("general.new"))
        end
        whitespace
      end
      problem_icon_tag(problems_including_files(@model).visible(problem_settings)) if policy(Problem).show?
    end
  end
end
