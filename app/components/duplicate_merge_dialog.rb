# frozen_string_literal: true

class Components::DuplicateMergeDialog < Components::Base
  include Phlex::Rails::Helpers::FormWith
  include Phlex::Rails::Helpers::ImageTag
  include Phlex::Rails::Helpers::NumberToHumanSize

  def initialize(problem:, model_a:, model_b:)
    @problem = problem
    @model_a = model_a
    @model_b = model_b
  end

  def view_template
    div(data: {controller: "duplicate-merge"}) do
      dialog(
        class: "max-w-[700px] w-full max-h-[90vh] overflow-auto rounded-2xl bg-secondary-50 dark:bg-[#1a1311] border border-secondary-200 dark:border-[#332623] shadow-xl p-0 text-secondary-900 dark:text-secondary-50 backdrop:bg-secondary-950/70",
        "aria-labelledby": "duplicate-merge-title",
        "aria-modal": "true",
        data: {duplicate_merge_target: "dialog"}
      ) do
        form_with url: merge_problem_path(@problem), method: :post, data: {turbo_frame: "_top"} do
          hidden_input("other_id", @model_b.public_id)
          header_block
          div(class: "flex flex-col gap-4 px-6 py-4") do
            keep_picker
            basic_information
            media
            taxonomy
            files
            publishing
          end
          footer_block
        end
      end
    end
  end

  private

  def hidden_input(name, value)
    input(type: "hidden", name: name, value: value)
  end

  def header_block
    div(class: "flex items-start justify-between gap-4 px-6 py-5 border-b border-secondary-200 dark:border-[#332623]") do
      div(class: "flex items-start gap-3 min-w-0") do
        span(class: "text-primary-500 mt-1") { Icon(icon: "files", label: t("problems.merge.title")) }
        div(class: "min-w-0") do
          h2(id: "duplicate-merge-title", class: "font-display text-xl font-bold m-0") { t("problems.merge.title") }
          p(class: "text-sm text-secondary-500 dark:text-secondary-400 m-0 mt-1 truncate") do
            plain "#{@model_a.name} ← → #{@model_b.name}"
          end
        end
      end
      button(
        type: "button",
        class: "inline-flex items-center justify-center size-8 rounded-md border border-secondary-300 dark:border-secondary-600 bg-transparent text-secondary-600 dark:text-secondary-200",
        data: {action: "click->duplicate-merge#close"},
        aria: {label: t("problems.merge.close")}
      ) { Icon(icon: "x-lg", label: t("problems.merge.close")) }
    end
  end

  def keep_picker
    section_card(t("problems.merge.keep_heading")) do
      div(class: "grid grid-cols-1 sm:grid-cols-2 gap-2") do
        keep_card("a", @model_a)
        keep_card("b", @model_b)
      end
      p(class: "text-xs text-secondary-500 dark:text-secondary-400 m-0") { t("problems.merge.keep_hint") }
    end
  end

  def keep_card(side, model)
    label(class: "flex items-start gap-2 p-3 rounded-md border border-secondary-200 dark:border-secondary-600 cursor-pointer has-[:checked]:border-primary-500") do
      input(
        type: "radio",
        name: "keep",
        value: side,
        checked: side == "a",
        class: "mt-0.5 border-secondary-300 text-primary-600 focus:ring-primary-500"
      )
      div(class: "min-w-0") do
        p(class: "font-semibold text-sm m-0 truncate") { model.name }
        p(class: "text-xs text-secondary-500 m-0 truncate") { model.path }
      end
    end
  end

  def basic_information
    section_card(t("problems.merge.basic")) do
      render Components::MergeFieldRow.new(field: "name", label: t("problems.merge.fields.name"), value_a: @model_a.name, value_b: @model_b.name)
      render Components::MergeFieldRow.new(field: "caption", label: t("problems.merge.fields.caption"), value_a: @model_a.caption, value_b: @model_b.caption)
      render Components::MergeFieldRow.new(field: "notes", label: t("problems.merge.fields.notes"), value_a: @model_a.notes, value_b: @model_b.notes, kind: :textarea)
    end
  end

  def media
    section_card(t("problems.merge.media")) do
      render Components::MergeFieldRow.new(
        field: "preview",
        label: t("problems.merge.fields.preview"),
        kind: :preview,
        value_a: preview_payload(@model_a, "A"),
        value_b: preview_payload(@model_b, "B")
      )
    end
  end

  def taxonomy
    section_card(t("problems.merge.taxonomy")) do
      render Components::MergeFieldRow.new(field: "creator_id", label: t("problems.merge.fields.creator"), value_a: @model_a.creator&.name, value_b: @model_b.creator&.name, override: false)
      render Components::MergeFieldRow.new(field: "library", label: t("problems.merge.fields.library"), value_a: @model_a.library.name, value_b: @model_b.library.name, kind: :readonly)
      if @model_a.library_id != @model_b.library_id
        p(class: "text-xs text-warning m-0") { t("problems.merge.library_stays") }
      end
      render Components::MergeFieldRow.new(field: "collection_id", label: t("problems.merge.fields.collection"), value_a: @model_a.collection&.name, value_b: @model_b.collection&.name, override: false)
      render Components::MergeFieldRow.new(
        field: "tags",
        label: t("problems.merge.fields.tags"),
        value_a: t("problems.merge.tag_count", count: @model_a.tag_list.size),
        value_b: t("problems.merge.tag_count", count: @model_b.tag_list.size),
        kind: :readonly
      )
      label(class: "flex flex-col gap-1 text-sm") do
        span(class: "text-[11px] font-medium uppercase tracking-wide text-secondary-500") { t("problems.merge.tag_strategy") }
        select(
          name: "tag_strategy",
          class: "rounded-md border border-secondary-300 dark:border-secondary-600 bg-white dark:bg-secondary-950 px-3 py-2 text-sm"
        ) do
          option(value: "combine", selected: true) { t("problems.merge.tag_combine") }
          option(value: "a") { t("problems.merge.tag_keep_a") }
          option(value: "b") { t("problems.merge.tag_keep_b") }
        end
      end
    end
  end

  def files
    section_card(t("problems.merge.files")) do
      p(class: "text-sm text-secondary-500 dark:text-secondary-400 m-0") { t("problems.merge.files_hint") }
      ul(class: "flex flex-col gap-1 m-0 p-0 list-none") do
        merged_files.each do |file|
          li(class: "flex items-center gap-2 text-sm text-secondary-800 dark:text-secondary-100") do
            span(class: "text-success") { Icon(icon: "check-circle", label: t("problems.merge.kept_file")) }
            span(class: "font-mono truncate") { file.filename }
            if file.size.to_i.positive?
              span(class: "text-xs text-secondary-500") { "(#{number_to_human_size(file.size)})" }
            end
          end
        end
      end
    end
  end

  def publishing
    section_card(t("problems.merge.publishing")) do
      render Components::MergeFieldRow.new(field: "license", label: t("problems.merge.fields.license"), value_a: @model_a.license, value_b: @model_b.license)
      render Components::MergeFieldRow.new(
        field: "sensitive",
        label: t("problems.merge.fields.sensitive"),
        value_a: sensitive_label(@model_a),
        value_b: sensitive_label(@model_b),
        override: false
      )
      render Components::MergeFieldRow.new(
        field: "indexable",
        label: t("problems.merge.fields.indexable"),
        value_a: indexable_label(@model_a),
        value_b: indexable_label(@model_b),
        override: false
      )
    end
  end

  def footer_block
    div(class: "flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 px-6 py-5 border-t border-secondary-200 dark:border-[#332623]") do
      p(class: "text-sm text-primary-600 dark:text-primary-400 m-0") { t("problems.merge.warning") }
      div(class: "flex items-center gap-2 shrink-0") do
        button(
          type: "button",
          class: [Components::BaseButton::BASE_CLASSES, Components::BaseButton::VARIANT_CLASSES["secondary"]].join(" "),
          data: {action: "click->duplicate-merge#close"}
        ) { t("general.cancel") }
        button(
          type: "submit",
          class: [Components::BaseButton::BASE_CLASSES, Components::BaseButton::VARIANT_CLASSES["success"]].join(" ")
        ) do
          Icon(icon: "box-arrow-in-up-left", label: t("problems.merge.confirm"))
          whitespace
          plain t("problems.merge.confirm")
        end
      end
    end
  end

  def section_card(title)
    section(class: "rounded-lg border border-secondary-200 dark:border-[#332623] bg-white/60 dark:bg-[#2d201c] p-4 flex flex-col gap-4") do
      h3(class: "text-[11px] font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400 m-0") { title }
      yield
    end
  end

  def preview_payload(model, side)
    file = model.preview_file
    src = if file&.is_image?
      model_model_file_path(model, file, format: file.extension, derivative: "preview")
    end
    {caption: t("problems.merge.preview_side", side: side), src: src}
  end

  def merged_files
    (@model_a.model_files.to_a + @model_b.model_files.to_a).uniq(&:id)
  end

  def sensitive_label(model)
    model.sensitive? ? t("problems.merge.on") : t("problems.merge.off")
  end

  def indexable_label(model)
    case model.indexable
    when "yes" then t("problems.merge.indexable_yes")
    when "no" then t("problems.merge.indexable_no")
    else t("problems.merge.indexable_inherit")
    end
  end
end
