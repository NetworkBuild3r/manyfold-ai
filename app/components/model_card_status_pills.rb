# frozen_string_literal: true

# Favorite / queue / printed pills on model cards. Always renders a stable
# id wrapper so turbo_stream can update after list toggles.
class Components::ModelCardStatusPills < Components::Base
  def initialize(model:)
    @model = model
  end

  def view_template
    return unless current_user

    queued = current_user.queued_model_ids.include?(@model.id)
    favorited = current_user.favorited_model_ids.include?(@model.id)
    printed = current_user.printed_model_ids.include?(@model.id)

    div(id: dom_id, class: "flex flex-col items-end gap-0.5 shrink-0") do
      if queued
        span(class: "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide bg-primary-600 text-white") { translate("components.model_card.queue") }
      end
      if printed
        span(class: "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide bg-success/15 text-success") { translate("components.model_card.printed") }
      end
      if favorited && !queued
        span(class: "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide bg-primary-100 text-primary-800 dark:bg-primary-900/40 dark:text-primary-300") { translate("components.model_card.favorite") }
      end
    end
  end

  def self.dom_id_for(model)
    "model_#{model.to_param}_status_pills"
  end

  private

  def dom_id
    self.class.dom_id_for(@model)
  end
end
