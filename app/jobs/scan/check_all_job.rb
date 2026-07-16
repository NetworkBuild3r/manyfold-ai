class Scan::CheckAllJob < ApplicationJob
  include JobIteration::Iteration

  queue_as :scan
  unique :until_executed

  # Rescan all models: filesystem sync + problem detection per model.
  # Does NOT re-analyse every file (that is what "deep" is for, and it OOMs large libs).
  def build_enumerator(filter_params, instigator, cursor:)
    scope = if instigator
      ModelPolicy::UpdateScope.new(instigator, Model).resolve
    else
      Model.all
    end
    scope = Search::FilterService.new(filter_params).models(scope)
    Rails.logger.info "[scan] queueing rescan for #{scope.count} models (deep=false)"
    enumerator_builder.active_record_on_records(scope, cursor: cursor)
  end

  def each_iteration(model, _filters, _instigator)
    # Shared batch id not required for rescan-all; each model is independent.
    model.check_later
  end
end
