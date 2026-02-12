# frozen_string_literal: true

module Problems
  class NoTags < Problems::Base
    Problems::Registry.register(:no_tags, self, "Model")

    class << self
      def detect(model)
        Problem.create_or_clear(model, :no_tags, model.tag_list.empty?)
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
        raise ArgumentError, "Unsupported action for NoTags: #{action.inspect}"
      end
    end
  end
end
