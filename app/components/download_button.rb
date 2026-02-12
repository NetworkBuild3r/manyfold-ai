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
    div(class: "tw:relative tw:inline-flex", data: {controller: "dropdown"}) do
      download_link html_class: "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-l-lg tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2 tw:bg-primary-600 tw:text-white tw:hover:bg-primary-700 tw:no-underline"
      button type: "button",
        data: {action: "click->dropdown#toggle"},
        class: "tw:inline-flex tw:items-center tw:justify-center tw:px-2 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-r-lg tw:border-l tw:border-primary-500 tw:bg-primary-600 tw:text-white tw:hover:bg-primary-700 tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2 tw:min-w-[44px] tw:min-h-[44px]",
        aria: {
          expanded: false,
          haspopup: "menu",
          controls: "download-menu"
        } do
        span(class: "tw:sr-only") { t("components.download_button.menu_header") }
      end
      ul class: "tw:absolute tw:right-0 tw:mt-1 tw:min-w-[10rem] tw:py-1 tw:bg-white tw:dark:bg-secondary-800 tw:rounded-lg tw:shadow-lg tw:border tw:border-secondary-200 tw:dark:border-secondary-600 tw:z-50",
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

  def download_link(selection: nil, file_type: nil, html_class: "tw:block tw:w-full tw:px-3 tw:py-2 tw:text-left tw:text-sm tw:text-secondary-700 tw:dark:text-secondary-200 tw:hover:bg-secondary-100 tw:dark:hover:bg-secondary-700 tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:no-underline")
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
        class: html_class + " tw:opacity-70 tw:cursor-not-allowed"
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
