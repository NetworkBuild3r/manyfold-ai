# frozen_string_literal: true

class Components::SearchHelp < Components::Base
  def view_template
    div(class: "text-left", data: {controller: "dialog"}) do
      a class: "text-primary-600 hover:underline focus-visible:ring-2 focus-visible:ring-primary-500 rounded no-underline",
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
    table(class: "w-full text-sm border-collapse") do
      tr do
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") { code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "cat hat" } }
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.simple") }
      end
      tr(class: "even:bg-secondary-50 dark:even:bg-secondary-800/50") do
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") { code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "cat or hat" } }
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.boolean") }
      end
      negation
      tr(class: "even:bg-secondary-50 dark:even:bg-secondary-800/50") do
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") { code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { '"cat hat"' } }
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.quotes") }
      end
      tr do
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") { code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "(cat or hat) and not bat" } }
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.parentheses") }
      end
      tr(class: "even:bg-secondary-50 dark:even:bg-secondary-800/50") do
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") { code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "tag = cat" } }
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.tag") }
      end
      tr do
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") { code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "!tag = cat" } }
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.without_tag") }
      end
      specific_fields
      tr(class: "even:bg-secondary-50 dark:even:bg-secondary-800/50") do
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") { code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "not set? tag" } }
        td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.unset") }
      end
      path
      filenames
      federation
    end
  end

  def path
    tr(class: "even:bg-secondary-50 dark:even:bg-secondary-800/50") do
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") do
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "path ~ tools" }
      end
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.path") }
      end
  end

  def filenames
    tr do
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") do
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "filename = cat.stl" }
        br
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "filename ~ cat" }
      end
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.filename") }
    end
  end

  def specific_fields
    tr do
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") do
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "creator ~ cat" }
        br
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "collection ~ cat" }
        br
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "caption ~ cat" }
        br
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "description ~ cat" }
        if SiteSettings.show_libraries?
          br
          code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "library = #{Library.first.name}" }
        end
      end
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.specific_fields") }
    end
  end

  def negation
    tr do
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") do
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "cat -hat" }
        br
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "cat !hat" }
        br
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "cat not hat" }
      end
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.negation") }
    end
  end

  def federation
    return unless SiteSettings.federation_enabled?
    tr(class: "even:bg-secondary-50 dark:even:bg-secondary-800/50") do
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2 pr-4") do
        code(class: "bg-secondary-100 dark:bg-secondary-700 px-1 py-0.5 rounded") { "@manyfold@3dp.chat" }
      end
      td(class: "border-b border-secondary-200 dark:border-secondary-600 py-2") { t("components.search_help.federation") }
    end
  end
end
