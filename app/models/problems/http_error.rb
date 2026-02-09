# frozen_string_literal: true

module Problems
  class HttpError < Problems::Base
    Problems::Registry.register(:http_error, self, "Link")

    class << self
      def detect(link, should_exist:, note: nil)
        opts = note.present? ? { note: note } : {}
        Problem.create_or_clear(link, :http_error, should_exist, opts)
      end
    end

    def resolve!(problem, action:)
      case action
      when :edit
        { redirect: edit_model_path(problem.problematic.linkable) }
      when :ignore
        problem.update!(ignored: true)
        { ignored: true }
      else
        raise ArgumentError, "Unsupported action for HttpError: #{action.inspect}"
      end
    end
  end
end
