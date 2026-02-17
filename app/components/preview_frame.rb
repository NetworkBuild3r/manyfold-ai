# frozen_string_literal: true

class Components::PreviewFrame < Components::Base
  include Phlex::Rails::Helpers::ImageTag
  include Phlex::Rails::Helpers::Sanitize

  register_value_helper :policy_scope

  def initialize(object:)
    @object = object
  end

  def before_template
    return if remote?
    @file = @object.is_a?(Model) ? @object.preview_file : policy_scope(@object.models).first&.preview_file
  end

  def view_template
    if @file
      render_local
    elsif remote?
      render_remote
    else
      empty
    end
  end

  private

  def remote?
    @object.is_a?(Federails::Actor) ? !@object.local : @object.remote?
  end

  def preview_container_class
    "block w-full aspect-[4/3] bg-secondary-100 dark:bg-secondary-800"
  end

  def image_class
    "w-full h-full object-cover" + (needs_hiding? ? " sensitive" : "")
  end

  def render_local
    if @file.is_image?
      div(class: preview_container_class) do
        image_tag model_model_file_path(@file.model, @file, format: @file.extension, derivative: "carousel"),
          class: image_class,
          alt: @file.name,
          loading: "lazy",
          decoding: "async"
      end
    elsif @file.is_renderable?
      div(class: "#{preview_container_class} #{"sensitive" if needs_hiding?}") do
        Renderer file: @file
      end
    else
      empty
    end
  end

  def render_remote
    actor = @object.is_a?(Federails::Actor) ? @object : @object.federails_actor
    preview_data = actor&.extensions&.dig("preview")
    case preview_data&.dig("type")
    when "Image"
      div(class: preview_container_class) do
        image_tag sanitize(preview_data["url"]),
          class: image_class,
          alt: sanitize(preview_data["summary"]),
          loading: "lazy",
          decoding: "async"
      end
    when "Document"
      div(class: "#{preview_container_class} #{"sensitive" if needs_hiding?}") do
        iframe(
          scrolling: "no",
          srcdoc: safe([
            "<html><body style=\"margin: 0; padding: 0; aspect-ratio: 1\">",
            preview_data["content"],
            "</body></html>"
          ].join),
          title: sanitize(preview_data["summary"]),
          class: "w-full h-full object-cover"
        )
      end
    else
      empty
    end
  end

  def needs_hiding?
    return false unless current_user.nil? || current_user.sensitive_content_handling.present?
    case @object.class
    when Model
      @object.sensitive
    when Collection
      @file.model.sensitive
    else
      false
    end
  end

  def empty
    div(class: "flex items-center justify-center block w-full aspect-[4/3] bg-secondary-100 dark:bg-secondary-800 text-secondary-400") do
      p(class: "text-sm") { t("components.model_card.no_preview") }
    end
  end
end
