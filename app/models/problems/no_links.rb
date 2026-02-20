# frozen_string_literal: true

module Problems
  class NoLinks < Problems::Base
    Problems::Registry.register(:no_links, self, "Model")

    class << self
      def detect(model)
        Problem.create_or_clear(model, :no_links, model.links.empty?)
      end
    end

    def resolve!(problem, action:)
      case action
      when :edit
        {redirect: edit_model_path(problem.problematic)}
      when :ignore
        problem.update!(ignored: true)
        {ignored: true}
      else
        raise ArgumentError, "Unsupported action for NoLinks: #{action.inspect}"
      end
    end
  end
end
