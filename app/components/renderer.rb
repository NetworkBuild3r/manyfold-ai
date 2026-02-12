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
    div class: "tw:relative", data: {turbo_permanent: true} do
      canvas id: "preview-file-#{@file.to_param}",
        class: "object-preview tw:relative tw:w-full tw:block",
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
      div class: "object-preview-progress tw:absolute tw:top-1/2 tw:left-1/2 tw:-translate-x-1/2 tw:-translate-y-1/2 tw:px-4 tw:py-2 tw:rounded-lg tw:bg-secondary-200 tw:dark:bg-secondary-700 tw:border tw:border-secondary-300 tw:dark:border-secondary-600",
        role: "presentation" do
        div class: "progress-bar tw:h-2 tw:bg-primary-500 tw:rounded tw:overflow-hidden tw:mb-2",
          role: "progressbar",
          style: "width: 0%",
          aria: {label: "Loading progress", valuenow: "0", valuemin: "0", valuemax: "100"}
        span class: "progress-label tw:text-sm tw:font-medium tw:block", role: "button" do
          span { t("renderer.load") }
          whitespace
          span { "(#{number_to_human_size @file.size, precision: 2})" }
        end
      end
    end
  end
end
