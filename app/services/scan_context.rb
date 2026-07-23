# frozen_string_literal: true

# Stamp scan-batch side-effect suppression on records before save/callbacks.
# Prefer explicit record flags over Current.* reads inside models.
module ScanContext
  module_function

  def apply!(*records)
    records.flatten.compact.each do |record|
      if record.respond_to?(:suppress_announce=)
        record.suppress_announce = true
      end
      if record.respond_to?(:suppress_problem_checks=)
        record.suppress_problem_checks = true
      end
      if record.respond_to?(:skip_problem_check=)
        record.skip_problem_check = true
      end
      if record.respond_to?(:suppress_attachment_refresh=)
        record.suppress_attachment_refresh = true
      end
    end
  end
end
