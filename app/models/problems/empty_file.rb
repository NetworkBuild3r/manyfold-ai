# frozen_string_literal: true

module Problems
  class EmptyFile < Problems::Base
    Problems::Registry.register(:empty, self, "ModelFile")

    class << self
      def detect(file)
        Problem.create_or_clear(file, :empty, file.size == 0)
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
        raise ArgumentError, "Unsupported action for EmptyFile: #{action.inspect}"
      end
    end
  end
end
