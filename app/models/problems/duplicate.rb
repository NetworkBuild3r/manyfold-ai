# frozen_string_literal: true

module Problems
  class Duplicate < Problems::Base
    Problems::Registry.register(:duplicate, self, "ModelFile")

    class << self
      def detect(file)
        Problem.create_or_clear(file, :duplicate, file.duplicate?)
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
        raise ArgumentError, "Unsupported action for Duplicate: #{action.inspect}"
      end
    end
  end
end
