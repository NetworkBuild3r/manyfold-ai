# frozen_string_literal: true

class Components::DownloadButton < Components::Base
  include Phlex::Rails::Helpers::LinkTo

  register_value_helper :policy

  def initialize(model:, format: :zip)
    @model = model
    @format = format
  end

  def render?
    policy(@model).download?
  end

  def before_template
    @extensions = @model.file_extensions.excluding("json")
    @has_supported_and_unsupported = @model.has_supported_and_unsupported?
  end

  def view_template
    div(class: "relative inline-flex", data: {controller: "dropdown"}) do
      download_link html_class: "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-l-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 bg-primary-600 text-white hover:bg-primary-700 no-underline"
      button type: "button",
        data: {action: "click->dropdown#toggle"},
        class: "inline-flex items-center justify-center px-2 py-1.5 text-sm font-medium rounded-r-lg border-l border-primary-500 bg-primary-600 text-white hover:bg-primary-700 focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 min-w-[44px] min-h-[44px]",
        aria: {
          expanded: false,
          haspopup: "menu",
          controls: "download-menu"
        } do
        span(class: "sr-only") { t("components.download_button.menu_header") }
      end
      ul class: Components::DropdownMenu.panel_class(align: :right, direction: :down),
        id: "download-menu",
        data: {dropdown_target: "menu"},
        role: "menu" do
        DropdownHeader text: t("components.download_button.menu_header")
        if @has_supported_and_unsupported
          li(role: "menuitem") { download_link selection: "supported" }
          li(role: "menuitem") { download_link selection: "unsupported" }
          DropdownDivider
        end
        @extensions&.compact&.map do |type|
          li(role: "menuitem") { download_link file_type: type }
        end
      end
    end
  end

  def download_link(selection: nil, file_type: nil, html_class: "block w-full px-3 py-2 text-left text-sm text-secondary-700 dark:text-secondary-200 hover:bg-secondary-100 dark:hover:bg-secondary-700 focus-visible:ring-2 focus-visible:ring-primary-500 no-underline")
    downloader = ArchiveDownloadService.new(model: @model, selection: selection || file_type)
    link_options = {
      class: html_class,
      rel: "nofollow",
      download: (downloader.ready? ? "download" : nil)
    }
    if downloader.preparing?
      link_options.merge!(
        disabled: true,
        "aria-disabled": "true",
        tabindex: -1,
        class: html_class + " opacity-70 cursor-not-allowed"
      )
    end
    link_to model_path(@model, format: @format, selection: selection || file_type), link_options do
      if downloader.ready?
        Icon(icon: "cloud-download-fill", label: t("components.download_button.download.ready"))
      elsif downloader.preparing?
        Icon(icon: "hourglass-split", label: t("components.download_button.download.preparing"), effect: "icon-flip")
      else
        Icon(icon: "cloud-download", label: t("components.download_button.download.missing"))
      end
      whitespace
      span do
        if file_type
          t("components.download_button.file_type", type: file_type.upcase)
        elsif selection
          # i18n-tasks-use t('components.download_button.supported')
          # i18n-tasks-use t('components.download_button.unsupported')
          t("components.download_button.%{selection}" % {selection: selection})
        else
          t("components.download_button.label")
        end
      end
    end
  end
end
