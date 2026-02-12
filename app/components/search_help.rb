# frozen_string_literal: true

class Components::SearchHelp < Components::Base
  def view_template
    div(class: "tw:text-left", data: {controller: "dialog"}) do
      a class: "tw:text-primary-600 tw:hover:underline tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:rounded tw:no-underline",
        aria: {haspopup: "dialog"},
        data: {action: "click->dialog#open"},
        tabindex: 0, href: "#" do
        yield
      end
      modal
    end
  end

  def modal
    Modal(id: "search-help", title: t("components.search_help.title")) do
      p do
        t("components.search_help.intro")
      end
      help_table
      p do
        t("components.search_help.more_details_html")
      end
    end
  end

  def help_table
    table(class: "tw:w-full tw:text-sm tw:border-collapse") do
      tr do
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") { code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "cat hat" } }
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.simple") }
      end
      tr(class: "tw:even:bg-secondary-50 tw:dark:even:bg-secondary-800/50") do
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") { code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "cat or hat" } }
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.boolean") }
      end
      negation
      tr(class: "tw:even:bg-secondary-50 tw:dark:even:bg-secondary-800/50") do
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") { code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { '"cat hat"' } }
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.quotes") }
      end
      tr do
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") { code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "(cat or hat) and not bat" } }
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.parentheses") }
      end
      tr(class: "tw:even:bg-secondary-50 tw:dark:even:bg-secondary-800/50") do
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") { code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "tag = cat" } }
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.tag") }
      end
      tr do
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") { code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "!tag = cat" } }
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.without_tag") }
      end
      specific_fields
      tr(class: "tw:even:bg-secondary-50 tw:dark:even:bg-secondary-800/50") do
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") { code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "not set? tag" } }
        td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.unset") }
      end
      path
      filenames
      federation
    end
  end

  def path
    tr(class: "tw:even:bg-secondary-50 tw:dark:even:bg-secondary-800/50") do
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") do
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "path ~ tools" }
      end
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.path") }
      end
  end

  def filenames
    tr do
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") do
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "filename = cat.stl" }
        br
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "filename ~ cat" }
      end
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.filename") }
    end
  end

  def specific_fields
    tr do
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") do
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "creator ~ cat" }
        br
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "collection ~ cat" }
        br
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "caption ~ cat" }
        br
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "description ~ cat" }
        if SiteSettings.show_libraries?
          br
          code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "library = #{Library.first.name}" }
        end
      end
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.specific_fields") }
    end
  end

  def negation
    tr do
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") do
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "cat -hat" }
        br
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "cat !hat" }
        br
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "cat not hat" }
      end
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.negation") }
    end
  end

  def federation
    return unless SiteSettings.federation_enabled?
    tr(class: "tw:even:bg-secondary-50 tw:dark:even:bg-secondary-800/50") do
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2 tw:pr-4") do
        code(class: "tw:bg-secondary-100 tw:dark:bg-secondary-700 tw:px-1 tw:py-0.5 tw:rounded") { "@manyfold@3dp.chat" }
      end
      td(class: "tw:border-b tw:border-secondary-200 tw:dark:border-secondary-600 tw:py-2") { t("components.search_help.federation") }
    end
  end
end
