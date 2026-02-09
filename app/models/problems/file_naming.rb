# frozen_string_literal: true

module Problems
  class FileNaming < Problems::Base
    Problems::Registry.register(:file_naming, self, "Model")

    class << self
      def detect(model, note: nil)
        should_exist = model.needs_organizing? && !model.contains_other_models?
        opts = { note: note.presence || model.formatted_path }
        Problem.create_or_clear(model, :file_naming, should_exist, opts)
      end
    end

    def resolve!(problem, action:)
      case action
      when :organize
        problem.update!(state: :resolving, in_progress: true)
        problem.problematic.organize_later(delay: 0)
        { in_progress: true }
      when :ignore
        problem.update!(ignored: true)
        { ignored: true }
      else
        raise ArgumentError, "Unsupported action for FileNaming: #{action.inspect}"
      end
    end
  end
end
