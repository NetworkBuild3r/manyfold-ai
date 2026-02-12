# frozen_string_literal: true

module Problems
  class MissingModel < Problems::Base
    Problems::Registry.register(:missing, self, "Model")

    class << self
      def detect(model)
        Problem.create_or_clear(model, :missing, !model.exists_on_storage?)
      end
    end

    def resolve!(problem, action:)
      case action
      when :destroy
        problematic = problem.problematic
        problem.destroy!
        problematic.delete_from_disk_and_destroy
        {removed: true}
      when :ignore
        problem.update!(ignored: true)
        {ignored: true}
      else
        raise ArgumentError, "Unsupported action for MissingModel: #{action.inspect}"
      end
    end
  end
end
