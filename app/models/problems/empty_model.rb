# frozen_string_literal: true

module Problems
  class EmptyModel < Problems::Base
    Problems::Registry.register(:empty, self, "Model")

    class << self
      def detect(model)
        Problem.create_or_clear(model, :empty, model.model_files.empty?)
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
        raise ArgumentError, "Unsupported action for EmptyModel: #{action.inspect}"
      end
    end
  end
end
