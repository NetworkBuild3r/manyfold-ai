# frozen_string_literal: true

class Components::PageTitle < Components::Base
  def initialize(title:, breadcrumbs: {}, heading: true)
    @title = title
    @breadcrumbs = breadcrumbs
    @heading = heading
  end

  def view_template
    nav aria: {label: "breadcrumb"}, class: "border-b border-secondary-200 dark:border-secondary-500 py-2" do
      ol class: "flex flex-wrap items-center gap-1 text-sm list-none m-0 p-0" do
        li class: "flex items-center gap-1" do
          a(href: root_url, class: "text-secondary-600 dark:text-secondary-300 no-underline hover:underline") { Icon icon: "house", label: t("application.navbar.home") }
        end
        @breadcrumbs.each do |text, path|
          li class: "flex items-center gap-1" do
            span(class: "text-secondary-400 dark:text-secondary-400") { "/" }
            a(href: path, class: "text-secondary-600 dark:text-secondary-300 no-underline hover:underline") { text }
          end
        end
        li(class: "flex items-center gap-1 font-medium text-secondary-900 dark:text-secondary-100", aria: {current: "page"}) do
          span(class: "text-secondary-400 dark:text-secondary-400") { "/" } if @breadcrumbs.any?
          span { @title }
        end
      end
    end
    if @heading
      h1(class: "text-2xl font-bold mt-2 mb-0 text-secondary-900 dark:text-secondary-100") do
        span { @title }
      end
    end
  end
end
