# frozen_string_literal: true

class Components::Renderer < Components::Base
  include Phlex::Rails::Helpers::JavascriptPath
  include Phlex::Rails::Helpers::NumberToHumanSize

  def initialize(file: nil, preview_url: nil, format: nil, size: nil, y_up: false, canvas_id: nil)
    @file = file
    @preview_url = preview_url
    @format = format
    @size = size
    @y_up = y_up
    @canvas_id = canvas_id
  end

  def render?
    return true if @preview_url.present?
    @file&.is_renderable?
  end

  def before_template
    @settings = current_user&.renderer_settings || SiteSettings::UserDefaults::RENDERER
  end

  def view_template
    # Avoid turbo_permanent: WebGL workers + offscreen canvases accumulate across
    # Turbo navigations and will not free GPU/heap memory.
    div class: "relative" do
      canvas id: canvas_element_id,
        class: "object-preview relative w-full block",
        tabindex: "0",
        data: {
          controller: "renderer",
          preview_url: resolved_preview_url,
          worker_url: javascript_path("offscreen_renderer.js"),
          format: resolved_format,
          y_up: resolved_y_up.to_s,
          grid_size_x: @settings["grid_width"],
          grid_size_z: @settings["grid_depth"],
          show_grid: @settings["show_grid"].to_s,
          enable_pan_zoom: @settings["enable_pan_zoom"].to_s,
          background_colour: @settings["background_colour"],
          object_colour: @settings["object_colour"],
          render_style: @settings["render_style"],
          auto_load: auto_load? ? "true" : "false",
          progress_aria_label: t("renderer.loading_progress"),
          load_label: t("renderer.load")
        }
      div class: "object-preview-progress absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 px-4 py-2 rounded-lg bg-secondary-200 dark:bg-secondary-700 border border-secondary-300 dark:border-secondary-600",
        role: "presentation" do
        div class: "progress-bar h-2 bg-primary-500 rounded overflow-hidden mb-2",
          role: "progressbar",
          style: "width: 0%",
          aria: {label: t("renderer.loading_progress"), valuenow: "0", valuemin: "0", valuemax: "100"}
        span class: "progress-label text-sm font-medium block", role: "button" do
          span { t("renderer.load") }
          whitespace
          span { "(#{number_to_human_size resolved_size, precision: 2})" } if resolved_size
        end
      end
    end
  end

  private

  def canvas_element_id
    @canvas_id.presence || "preview-file-#{@file.to_param}"
  end

  def resolved_preview_url
    @preview_url.presence || model_model_file_by_filename_path(@file.model, @file.filename)
  end

  def resolved_format
    @format.presence || @file.extension
  end

  def resolved_y_up
    @file ? @file.y_up : @y_up
  end

  def resolved_size
    @size || @file&.size
  end

  def auto_load?
    max_mb = @settings["auto_load_max_size"]
    max_mb = SiteSettings::UserDefaults::RENDERER[:auto_load_max_size] if max_mb.nil?
    return false if max_mb.to_i <= 0

    size = resolved_size
    return false if size.nil?

    size < max_mb.to_i.megabytes
  end
end
