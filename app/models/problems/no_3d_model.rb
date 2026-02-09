# frozen_string_literal: true

module Problems
  class No3dModel < Problems::Base
    Problems::Registry.register(:no_3d_model, self, "Model")

    class << self
      def detect(model)
        Problem.create_or_clear(model, :no_3d_model, model.three_d_files.empty?)
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
        raise ArgumentError, "Unsupported action for No3dModel: #{action.inspect}"
      end
    end
  end
end
