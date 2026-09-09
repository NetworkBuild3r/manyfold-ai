# frozen_string_literal: true

class Components::ProblemRow < Components::Base
  include Phlex::Rails::Helpers::ImageTag
  include Phlex::Rails::Helpers::LinkTo
  include Phlex::Rails::Helpers::NumberToHumanSize

  def initialize(problem:, user:, pair: nil)
    @problem = problem
    @user = user
    @pair = pair
  end

  def view_template
    div(
      id: "problem-#{@problem.id}",
      class: row_class,
      data: {
        problem_list_filter_target: "row",
        search: search_blob,
        merge_url: merge_url
      }
    ) do
      yield if block_given?
      if paired?
        pair_block
      else
        thumbnail(preview_image_file, title_text)
        info_block(title_text, file_name, file_size, secondary_label, view_href)
      end
      view_button
      div(class: "flex items-center gap-2 shrink-0") do
        merge_button
        ResolveButton(problem: @problem, user: @user)
        ignore_button
      end
    end
  end

  private

  def row_class
    [
      "problem-row flex flex-wrap md:flex-nowrap items-center gap-3 md:gap-4 w-full p-3 rounded-md border",
      "bg-secondary-50 dark:bg-secondary-800/60",
      "border-secondary-200 dark:border-secondary-600",
      "has-[:checked]:border-primary-500 has-[:checked]:bg-primary-500/10",
      ("opacity-50" if @problem.ignored)
    ].compact.join(" ")
  end

  def search_blob
    [
      title_text,
      file_name,
      counterpart_model_name,
      counterpart_file_name,
      @problem.note,
      @problem.category
    ].compact.join(" ").downcase
  end

  def paired?
    @pair.present? && other_file.present?
  end

  def pair_block
    div(class: "min-w-0 flex-1 grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-2 sm:gap-3 items-center") do
      side(model: preview_model, file: model_file, href: view_href)
      versus
      side(model: other_file.model, file: other_file, href: [other_file.model, other_file], extra: extra_copies_label)
    end
  end

  def versus
    span(class: "justify-self-center text-[10px] font-bold uppercase tracking-wide text-secondary-400 dark:text-secondary-500 px-1") do
      t("problems.index.versus")
    end
  end

  def side(model:, file:, href:, extra: nil)
    div(class: "min-w-0 flex items-center gap-3 p-2 rounded-md border border-secondary-200 dark:border-secondary-600 bg-white/70 dark:bg-secondary-900/50") do
      thumbnail(preview_for(model), model&.name.to_s)
      info_block(model&.name.presence || title_text, file&.filename.presence || file&.name, file&.size, extra, href)
    end
  end

  def thumbnail(image_file, alt)
    div(class: "relative w-16 h-12 shrink-0 overflow-hidden rounded border border-secondary-200 dark:border-secondary-600 bg-secondary-100 dark:bg-secondary-900") do
      if image_file
        image_tag(
          model_model_file_path(image_file.model, image_file, format: image_file.extension, derivative: "preview"),
          alt: alt,
          class: "absolute inset-0 w-full h-full object-cover",
          loading: "lazy",
          decoding: "async",
          width: 64,
          height: 48
        )
      else
        span(class: "absolute inset-0 flex items-center justify-center text-secondary-400") do
          Icon(icon: "box", label: t("problems.index.no_preview"))
        end
      end
    end
  end

  def info_block(title, filename, size, extra, href)
    div(class: "min-w-0 flex-1 flex flex-col gap-1") do
      if href
        link_to title, href, class: "font-semibold text-sm text-primary-600 dark:text-primary-400 no-underline hover:underline truncate"
      else
        p(class: "font-semibold text-sm text-primary-600 dark:text-primary-400 truncate") { title }
      end
      div(class: "flex flex-wrap items-center gap-2 text-xs text-secondary-500 dark:text-secondary-400 min-w-0") do
        Icon(icon: "file-earmark", label: t("problems.index.file"))
        span(class: "font-mono truncate max-w-[16rem]") { filename.to_s }
        if size.to_i.positive?
          span { "(#{number_to_human_size(size)})" }
        end
        if extra.present?
          span { "•" }
          span(class: "truncate") { extra }
        end
      end
    end
  end

  def merge_button
    return unless merge_url

    GoButton(
      label: t("problems.index.merge"),
      href: merge_url,
      variant: "success",
      icon: "box-arrow-in-up-left",
      data: {turbo_frame: "duplicate-merge-dialog"}
    )
  end

  def merge_url
    return unless @pair&.mergeable? && @user && ProblemPolicy.new(@user, @problem).merge?

    merge_problem_path(@problem, return_to: problems_list_return_to)
  end

  def problems_list_return_to
    request = helpers.request
    return problems_path if request.blank?
    return request.fullpath if ["/problems", "/problems/index"].include?(request.path)

    problems_path
  end

  def extra_copies_label
    extra = @pair.counterparts.size - 1
    return if extra < 1

    t("problems.index.more_copies", count: extra)
  end

  def view_button
    if view_href
      link_to view_href,
        class: "inline-flex items-center justify-center size-[30px] shrink-0 rounded-md border border-secondary-300 dark:border-secondary-600 bg-white dark:bg-secondary-900 text-secondary-700 dark:text-secondary-100 hover:bg-secondary-50 dark:hover:bg-secondary-700 no-underline focus-visible:ring-2 focus-visible:ring-primary-500",
        aria: {label: t("problems.index.view")} do
        Icon(icon: "eye", label: t("problems.index.view"))
      end
    else
      span(class: "size-[30px] shrink-0")
    end
  end

  def ignore_button
    if @problem.ignored
      link_to problem_path(@problem, problem: {ignored: false}),
        method: :patch,
        class: ignore_button_class,
        aria: {label: t("problems.index.unignore")} do
        Icon(icon: "eye-fill", label: t("problems.index.unignore"))
      end
    else
      link_to problem_path(@problem, problem: {ignored: true}),
        method: :patch,
        class: ignore_button_class,
        data: {action: "click->problem-list-filter#hideRow"},
        aria: {label: t("problems.index.ignore")} do
        Icon(icon: "eye-slash", label: t("problems.index.ignore"))
      end
    end
  end

  def ignore_button_class
    "inline-flex items-center justify-center size-[30px] shrink-0 rounded-md border border-secondary-300 dark:border-secondary-600 bg-white dark:bg-secondary-900 text-secondary-700 dark:text-secondary-100 hover:bg-secondary-50 dark:hover:bg-secondary-700 no-underline focus-visible:ring-2 focus-visible:ring-primary-500"
  end

  def title_text
    preview_model&.name.presence || @problem.problematic.try(:name).presence || @problem.problematic.try(:url).to_s
  end

  def file_name
    if model_file
      model_file.filename.presence || model_file.name
    else
      t("problems.%{type}.%{category}.title" % {type: @problem.problematic_type.underscore, category: @problem.category})
    end
  end

  def file_size
    model_file&.size
  end

  def secondary_label
    @problem.note.presence
  end

  def view_href
    if model_file && preview_model
      [preview_model, model_file]
    elsif preview_model
      preview_model
    elsif @problem.problematic.respond_to?(:to_model)
      @problem.problematic
    end
  end

  def model_file
    @problem.problematic if @problem.problematic.is_a?(ModelFile)
  end

  def other_file
    @pair&.primary_other_file
  end

  def counterpart_model_name
    other_file&.model&.name
  end

  def counterpart_file_name
    other_file&.filename
  end

  def preview_model
    case @problem.problematic
    when Model then @problem.problematic
    when ModelFile then @problem.problematic.model
    else
      parent = @problem.parent
      parent if parent.is_a?(Model)
    end
  end

  def preview_image_file
    preview_for(preview_model)
  end

  def preview_for(model)
    file = model&.preview_file
    file if file&.is_image?
  end
end
