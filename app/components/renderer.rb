# frozen_string_literal: true

class Components::Renderer < Components::Base
  include Phlex::Rails::Helpers::JavascriptPath
  include Phlex::Rails::Helpers::NumberToHumanSize

  def initialize(file:)
    @file = file
  end

  def render?
    @file&.is_renderable?
  end

  def before_template
    @settings = current_user&.renderer_settings || SiteSettings::UserDefaults::RENDERER
  end

  def view_template
    div class: "relative", data: {turbo_permanent: true} do
      canvas id: "preview-file-#{@file.to_param}",
        class: "object-preview relative w-full block",
        tabindex: "0",
        data: {
          controller: "renderer",
          preview_url: model_model_file_by_filename_path(@file.model, @file.filename),
          worker_url: javascript_path("offscreen_renderer.js"),
          format: @file.extension,
          y_up: @file.y_up.to_s,
          grid_size_x: @settings["grid_width"],
          grid_size_z: @settings["grid_depth"],
          show_grid: @settings["show_grid"].to_s,
          enable_pan_zoom: @settings["enable_pan_zoom"].to_s,
          background_colour: @settings["background_colour"],
          object_colour: @settings["object_colour"],
          render_style: @settings["render_style"],
          auto_load: ((@file.size || 9_999_999.megabytes) < (@settings["auto_load_max_size"] || 9_999_999).megabytes) ? "true" : "false"
        }
      div class: "object-preview-progress absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 px-4 py-2 rounded-lg bg-secondary-200 dark:bg-secondary-700 border border-secondary-300 dark:border-secondary-600",
        role: "presentation" do
        div class: "progress-bar h-2 bg-primary-500 rounded overflow-hidden mb-2",
          role: "progressbar",
          style: "width: 0%",
          aria: {label: "Loading progress", valuenow: "0", valuemin: "0", valuemax: "100"}
        span class: "progress-label text-sm font-medium block", role: "button" do
          span { t("renderer.load") }
          whitespace
          span { "(#{number_to_human_size @file.size, precision: 2})" }
        end
      end
    end
  end
end
