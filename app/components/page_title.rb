# frozen_string_literal: true

class Components::PageTitle < Components::Base
  def initialize(title:, breadcrumbs: {}, heading: true)
    @title = title
    @breadcrumbs = breadcrumbs
    @heading = heading
  end

  def view_template
    nav aria: {label: "breadcrumb"}, class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2" do
      ol class: "tw:flex tw:flex-wrap tw:items-center tw:gap-1 tw:text-sm tw:list-none tw:m-0 tw:p-0" do
        li class: "tw:flex tw:items-center tw:gap-1" do
          a(href: root_url, class: "tw:text-secondary-600 tw:dark:text-secondary-400 tw:no-underline hover:tw:underline") { Icon icon: "house", label: t("application.navbar.home") }
        end
        @breadcrumbs.each do |text, path|
          li class: "tw:flex tw:items-center tw:gap-1" do
            span(class: "tw:text-secondary-400 tw:dark:text-secondary-500") { "/" }
            a(href: path, class: "tw:text-secondary-600 tw:dark:text-secondary-400 tw:no-underline hover:tw:underline") { text }
          end
        end
        li(class: "tw:flex tw:items-center tw:gap-1 tw:font-medium tw:text-secondary-900 tw:dark:text-secondary-100", aria: {current: "page"}) do
          span(class: "tw:text-secondary-400 tw:dark:text-secondary-500") { "/" } if @breadcrumbs.any?
          span { @title }
        end
      end
    end
    if @heading
      h1(class: "tw:text-xl tw:font-semibold tw:mt-2 tw:mb-0") do
        span { @title }
      end
    end
  end
end
