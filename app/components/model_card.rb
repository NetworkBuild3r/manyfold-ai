# frozen_string_literal: true

class Components::ModelCard < Components::Base
  include Phlex::Rails::Helpers::ImageTag
  include Phlex::Rails::Helpers::Sanitize
  include Phlex::Rails::Helpers::LinkTo

  register_output_helper :server_indicator
  register_value_helper :policy

  def initialize(model:, eager_preview: false, gallery: false)
    @model = model
    @actor = @model.federails_actor
    @eager_preview = eager_preview
    @gallery = gallery
  end

  def before_template
    @editable = policy(@model).edit?
  end

  def view_template
    # Only animate shadow/transform — transition-all also animates height when the
    # CSS grid stretches a last incomplete row as infinite-scroll appends cards.
    classes = "model-card relative flex flex-col rounded-xl overflow-hidden bg-surface dark:bg-surface-dark border border-secondary-200 dark:border-secondary-600 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-[box-shadow,transform] duration-200"

    div(id: self.class.dom_id_for(@model), class: classes, role: "listitem") do
      div(class: "absolute top-0 left-0 right-0 z-10 px-2 py-1 bg-secondary-200/90 dark:bg-secondary-700/90 text-sm") { server_indicator @model } if @model.remote?
      ModelCardPreview(model: @model, editable: @editable, actor: @actor, eager_preview: @eager_preview, gallery: @gallery)
      div(class: "p-3 flex flex-col gap-1 grow") do
        title_row
        creator_line
        tag_peek
      end
      ModelCardActions(model: @model, editable: @editable, actor: @actor)
    end
  end

  def self.dom_id_for(model)
    "model_#{model.to_param}"
  end

  def self.dom_id_for_param(param)
    "model_#{param}"
  end

  private

  def title_row
    div(class: "flex items-start gap-2") do
      div(class: "min-w-0 flex-1 font-semibold text-secondary-900 dark:text-secondary-100 leading-snug line-clamp-2") do
        if @editable
          EditableSpan(fieldname: "model[name]", path: model_path(@model), text: @model.name)
        else
          link_to @model.name, @model, class: "text-inherit no-underline hover:underline", data: {turbo_frame: "_top"}, "aria-label": translate("components.model_card.open_button.label", name: @model.name)
        end
        if @model.sensitive
          whitespace
          Icon(icon: "explicit", label: Model.human_attribute_name(:sensitive))
        end
        whitespace
        AccessIndicator(object: @model)
        whitespace
        StatusBadges(model: @model)
      end
      ModelCardStatusPills(model: @model) if current_user
    end
  end

  def creator_line
    name = if @actor && !@actor.local
      @actor.extensions.dig("attributedTo", "name")
    else
      @model.creator&.name
    end
    return if name.blank? && @model.collection.blank?

    div(class: "text-xs text-secondary-500 dark:text-secondary-400 truncate") do
      if name.present?
        if @model.creator
          link_to name.careful_titleize, @model.creator, class: "text-inherit no-underline hover:underline", data: {turbo_frame: "_top"}
        else
          span { name }
        end
      end
      if @model.collection
        span(class: "text-secondary-400") { name.present? ? " · " : "" }
        link_to @model.collection.name, @model.collection, class: "text-inherit no-underline hover:underline", data: {turbo_frame: "_top"}
      end
    end
  end

  def tag_peek
    tags = @model.tags.first(3)
    return if tags.empty?

    div(class: "flex flex-wrap gap-1 mt-auto pt-0.5") do
      tags.each do |tag|
        link_to tag.name,
          models_path(tag: [tag.name]),
          class: "inline-flex max-w-[7rem] truncate px-1.5 py-0.5 rounded text-[11px] bg-secondary-100 dark:bg-secondary-800 text-secondary-600 dark:text-secondary-300 no-underline hover:bg-primary-100 hover:text-primary-800 dark:hover:bg-primary-900/40",
          data: {turbo_frame: "_top"}
      end
    end
  end
end
