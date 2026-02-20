class Current < ActiveSupport::CurrentAttributes
  # When true, callbacks should avoid enqueuing problem-checking jobs.
  attribute :skip_problem_checks

  # Optional identifier used to group related scan jobs.
  attribute :scan_batch_id
end
