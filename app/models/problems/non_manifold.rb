# frozen_string_literal: true

module Problems
  class NonManifold < Problems::Base
    Problems::Registry.register(:non_manifold, self, "ModelFile")

    class << self
      def detect(file, should_exist:)
        Problem.create_or_clear(file, :non_manifold, should_exist)
      end
    end

    def resolve!(problem, action:)
      case action
      when :show
        {redirect: model_model_file_path(problem.problematic.model, problem.problematic)}
      when :ignore
        problem.update!(ignored: true)
        {ignored: true}
      else
        raise ArgumentError, "Unsupported action for NonManifold: #{action.inspect}"
      end
    end
  end
end
