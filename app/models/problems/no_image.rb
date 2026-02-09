# frozen_string_literal: true

module Problems
  class NoImage < Problems::Base
    Problems::Registry.register(:no_image, self, "Model")

    class << self
      def detect(model)
        Problem.create_or_clear(model, :no_image, model.image_files.empty?)
      end
    end

    def resolve!(problem, action:)
      case action
      when :upload
        { redirect: model_path(problem.problematic, anchor: "upload-form") }
      when :ignore
        problem.update!(ignored: true)
        { ignored: true }
      else
        raise ArgumentError, "Unsupported action for NoImage: #{action.inspect}"
      end
    end
  end
end
