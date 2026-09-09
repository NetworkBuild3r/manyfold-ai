class ProblemsController < ApplicationController
  skip_after_action :verify_authorized, only: :resolve
  after_action :verify_policy_scoped, only: [:resolve, :merge, :apply_merge]

  def index
    authorize Problem
    # Are we showing ignored problems?
    @show_ignored = (params[:show_ignored] == "true")
    query = @show_ignored ? policy_scope(Problem.including_ignored) : policy_scope(Problem)
    # Now, which page are we on?
    page = params[:page] || 1
    # What categories are we showing?
    # First, get the possible categories based on severity filter
    severities = params[:severity] ? Problem::CATEGORIES.select { |cat| params[:severity]&.include?(current_user.problem_severity(cat).to_s) } : nil # rubocop:disable Pundit/UsePolicyScope
    # Then get the category filter
    categories = params[:category]&.map(&:to_sym)
    # Now query with the intersection of the two, or if we don't have both, then whichever we do have
    if categories.present? || severities.present?
      combined = (categories.present? && severities.present?) ?
        (categories.intersection(severities)) :
        [[categories], [severities]].flatten.compact
      query = query.where(category: combined)
    end
    # What object types are we showing?
    query = query.where(problematic_type: params[:type].map(&:classify)) if params[:type]
    # Don't show types ignored in user settings
    query = query.visible(helpers.problem_settings)
    query = query.includes([:problematic])
    counts_query = query.except(:includes, :preload, :eager_load, :order)
    @counts_by_category = counts_query.group(:category).count
    @duplicate_list = counts_query.exists? && !counts_query.where.not(category: "duplicate").exists?
    per_page = params[:per_page]&.to_i
    per_page = 50 unless per_page&.positive?
    @problems = if @duplicate_list
      query.where(id: Problem::DuplicateGroup.representative_ids(query))
        .page(page).per(per_page).order(:id)
        .includes(problematic: [:library, :model])
    else
      query.page(page).per(per_page).order([:category, :problematic_type])
        .includes(problematic: [:library, :model])
    end
    @recoverable_bytes = if @duplicate_list
      Problem::DuplicateGroup.recoverable_bytes(query, policy_scope(ModelFile))
    else
      recoverable_bytes_for(@problems)
    end
    @duplicate_pairs = Problem::DuplicatePair.map_for(@problems, policy_scope(ModelFile))
    # Do we have any filters at all?
    @filters_applied = [:show_ignored, :severity, :category, :type].any? { |k| params.has_key?(k) }
  end

  def update
    @problem = Problem.including_ignored.find_param(params[:id])
    authorize @problem
    @problem.update!(permitted_params)
    notice = t(
      (@problem.ignored ? ".ignored" : ".unignored"),
      name: @problem.problematic.name,
      message: translate("problems.%{type}.%{category}.title" % {type: @problem.problematic_type.underscore, category: @problem.category})
    )
    redirect_back_or_to problems_path, notice: notice
  end

  def resolve
    ids = params[:id] ? [params[:id]] : params["problems"]&.select { |_k, v| v == "1" }&.keys || []
    @problems = policy_scope(Problem).where(public_id: ids).to_a
    bulk = @problems.size > 1

    if params[:resolve]
      result = Problem.resolve_batch(@problems)
      handle_resolve_result(result, bulk)
    elsif params[:ignore]
      result = Problem.resolve_batch(@problems, override_action: :ignore)
      handle_resolve_result(result, bulk)
    else
      redirect_back_or_to problems_path unless performed?
    end
  end

  def merge
    @problem = policy_scope(Problem).find_param(params[:id])
    authorize @problem, :merge?
    @pair = Problem::DuplicatePair.build(@problem)
    @model_a = @pair.model
    @model_b = @pair.other_model_for(params[:other_id])
    if @model_b.blank?
      redirect_to problems_path, alert: t(".no_counterpart")
      return
    end
    authorize @model_a, :merge?
    authorize @model_b, :merge?
  end

  def apply_merge
    @problem = policy_scope(Problem).find_param(params[:id])
    authorize @problem, :merge?
    pair = Problem::DuplicatePair.build(@problem)
    model_a = pair.model
    model_b = pair.other_model_for(params[:other_id])
    if model_b.blank?
      redirect_to problems_path, alert: t("problems.merge.no_counterpart")
      return
    end
    authorize model_a, :merge?
    authorize model_b, :merge?
    target, source = (params[:keep].to_s == "b") ? [model_b, model_a] : [model_a, model_b]
    Model::MergeWithChoices.call(
      target: target,
      source: source,
      choices: merge_field_choices,
      overrides: merge_overrides,
      tag_strategy: params[:tag_strategy]
    )
    redirect_to problems_path, notice: t("problems.merge.success", name: target.name)
  end

  private

  def handle_resolve_result(result, bulk)
    if result[:redirect].present? && !bulk && !performed?
      redirect_to result[:redirect]
      return
    end

    ids_to_remove = result[:removed_ids] + result[:ignored_ids]
    if request.format.turbo_stream? && ids_to_remove.any? && !performed?
      render turbo_stream: build_resolve_turbo_streams(ids_to_remove)
      return
    end

    redirect_back_or_to problems_path unless performed?
  end

  def build_resolve_turbo_streams(ids_to_remove)
    streams = ids_to_remove.map { |id| turbo_stream.remove("problem-#{id}") }
    # When resolving from the model page, replace the problems card so the count updates.
    if params[:from] == "model" && params[:model_id].present?
      model = Model.find_by(public_id: params[:model_id])
      if model && policy(:problem).show?
        streams << turbo_stream.replace("model-problems-card", partial: "application/problems_card", locals: {
          problematic: model,
          problems: model.problems.visible(helpers.problem_settings),
          show_when_empty: true,
          card_id: "model-problems-card",
          from_model: model,
          nesting_models: (model.contained_models if model.contains_other_models?)
        })
      end
    end
    streams
  end

  def permitted_params
    params.expect(problem: [
      :ignored
    ])
  end

  def merge_field_choices
    fields = params[:fields]
    choices = fields.respond_to?(:permit) ? fields.permit(*Model::MergeWithChoices::FIELD_KEYS).to_h : {}
    merge_overrides.each do |key, value|
      next if value.blank?

      choices[key] = "override"
    end
    choices
  end

  def merge_overrides
    overrides = params[:overrides]
    return {} unless overrides.respond_to?(:permit)

    overrides.permit(*Model::MergeWithChoices::FIELD_KEYS).to_h
  end

  def recoverable_bytes_for(problems)
    file_ids = problems.filter_map { |problem| problem.problematic_id if problem.problematic_type == "ModelFile" }
    return 0 if file_ids.empty?

    policy_scope(ModelFile).where(id: file_ids).sum(:size).to_i
  end
end
