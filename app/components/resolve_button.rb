# frozen_string_literal: true

class Components::ResolveButton < Components::Base
  include Phlex::Rails::Helpers::ButtonTo

  OPTIONS = {
    show: {
      icon: "box",
      i18n_key: "models.file.open_button.text", # i18n-tasks-use t('models.file.open_button.text')
      button_type: "primary"
    },
    edit: {
      icon: "pencil",
      i18n_key: "general.edit", # i18n-tasks-use t('general.edit')
      button_type: "primary"
    },
    destroy: {
      icon: "trash",
      i18n_key: "general.delete", # i18n-tasks-use t('general.delete')
      button_type: "danger",
      confirm: "%{type}s.destroy.confirm"
    },
    merge: {
      icon: "box-arrow-in-up-left",
      i18n_key: "models.problem.merge_all", # i18n-tasks-use t('models.problem.merge_all')
      button_type: "danger"
    },
    upload: {
      icon: "upload",
      i18n_key: "application.navbar.upload", # i18n-tasks-use t('application.navbar.upload')
      button_type: "primary"
    },
    convert: {
      icon: "arrow-left-right",
      i18n_key: "model_files.show.convert", # i18n-tasks-use t('model_files.show.convert')
      button_type: "warning"
    },
    organize: {
      icon: "folder-check",
      i18n_key: "models.organize.label", # i18n-tasks-use t('models.organize.label')
      button_type: "warning",
      confirm: "models.organize.confirm" # i18n-tasks-use t('models.organize.confirm')
    }
  }

  def initialize(problem:, user: nil, from_model: nil)
    @problem = problem
    @user = user
    @from_model = from_model
  end

  def before_template
    @options = OPTIONS[@problem.resolution_strategy.to_sym]
    @text = t @options[:i18n_key]
  end

  def resolve_url
    opts = {resolve: true, format: :turbo_stream}
    opts[:from] = "model" if @from_model
    opts[:model_id] = @from_model.id if @from_model
    resolve_problem_path(@problem, opts)
  end

  def view_template
    if @problem.in_progress || @problem.resolving?
      button_to("#", class: "#{resolve_button_base_class} #{resolve_button_variant_class} tw:opacity-70 tw:cursor-not-allowed", disabled: true) do
        span(class: "tw:animate-spin tw:inline-block tw:w-4 tw:h-4 tw:border-2 tw:border-current tw:border-t-transparent tw:rounded-full") { "" }
        whitespace
        span { @text }
      end
    else
      DoButton(
        label: @text,
        href: resolve_url,
        variant: @options[:button_type],
        icon: @options[:icon],
        method: :post,
        confirm: @options[:confirm] ? translate(@options[:confirm] % {type: @problem.problematic_type.underscore}) : nil,
        nofollow: true
      )
    end
  end

  def render?
    ProblemPolicy.new(@user, @problem).resolve?
  end

  private

  def resolve_button_base_class
    "tw:inline-flex tw:items-center tw:gap-1.5 tw:px-3 tw:py-1.5 tw:text-sm tw:font-medium tw:rounded-lg tw:transition-colors tw:focus-visible:ring-2 tw:focus-visible:ring-primary-500 tw:focus-visible:ring-offset-2"
  end

  def resolve_button_variant_class
    case @options[:button_type]
    when "primary" then "tw:bg-primary-600 tw:text-white tw:hover:bg-primary-700"
    when "danger" then "tw:bg-danger tw:text-white tw:hover:opacity-90"
    when "warning" then "tw:bg-warning tw:text-secondary-900 tw:hover:opacity-90"
    else "tw:bg-primary-600 tw:text-white tw:hover:bg-primary-700"
    end
  end
end
