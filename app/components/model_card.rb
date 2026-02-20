# frozen_string_literal: true

class Components::ModelCard < Components::Base
  include Phlex::Rails::Helpers::ImageTag
  include Phlex::Rails::Helpers::Sanitize
  include Phlex::Rails::Helpers::LinkTo

  register_output_helper :server_indicator
  register_value_helper :policy

  def initialize(model:)
    @model = model
    @actor = @model.federails_actor
  end

  def before_template
    @editable = policy(@model).edit?
  end

  def view_template
    div(class: "model-card relative flex flex-col rounded-xl overflow-hidden bg-surface dark:bg-surface-dark border border-secondary-200 dark:border-secondary-600 shadow-sm hover:shadow-md transition-shadow") do
      div(class: "absolute top-0 left-0 right-0 z-10 px-2 py-1 bg-secondary-200/90 dark:bg-secondary-700/90 text-sm") { server_indicator @model } if @model.remote?
      ModelCardPreview(model: @model, editable: @editable, actor: @actor)
      div(class: "p-3 flex flex-col gap-1") { info_row }
      ModelCardActions(model: @model, editable: @editable, actor: @actor)
    end
  end

  private

  def title
    div(class: "font-medium text-secondary-900 dark:text-secondary-100") do
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
    end
  end

  def credits
    ul(class: "list-none flex flex-wrap gap-x-2 text-xs text-secondary-500 dark:text-secondary-400 m-0 p-0") do
      if @actor && !@actor.local
        if (creator = @actor.extensions["attributedTo"])
          li { creator target: creator["url"], name: creator["name"] }
        end
        if (collection = @actor.extensions["context"])
          li { collection target: collection["url"], name: collection["name"] }
        end
      else
        li { creator target: @model.creator, name: @model.creator.name } if @model.creator
        li { collection target: @model.collection, name: @model.collection.name } if @model.collection
      end
    end
  end

  def creator(target:, name:)
    Icon icon: "person", label: Creator.model_name.human
    whitespace
    link_to name, target, "aria-label": [Creator.model_name.human, name].join(": "), data: {turbo_frame: "_top"}
  end

  def collection(target:, name:)
    Icon icon: "collection", label: Collection.model_name.human
    whitespace
    link_to name, target, "aria-label": [Collection.model_name.human, name].join(": "), data: {turbo_frame: "_top"}
  end

  def caption
    if (summary = @model.try(:caption) || @actor&.extensions&.dig("summary"))
      span(class: "text-sm text-secondary-500 dark:text-secondary-400") do
        sanitize summary.split("</p>", 2).first
      end
    end
  end

  def info_row
    div(class: "flex flex-wrap items-start gap-x-2 gap-y-1") do
      div(class: "min-w-0 flex-1") do
        title
        caption
      end
      div(class: "flex-shrink-0") do
        small { credits }
      end
    end
  end
end
