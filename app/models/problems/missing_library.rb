# frozen_string_literal: true

module Problems
  class MissingLibrary < Problems::Base
    Problems::Registry.register(:missing, self, "Library")

    class << self
      def detect(library)
        Problem.create_or_clear(library, :missing, !library.storage_exists?)
      end
    end

    def resolve!(problem, action:)
      case action
      when :destroy
        problematic = problem.problematic
        problem.destroy!
        # A library has no single on-disk path to delete (it might be missing, remote, etc);
        # destroying the record (and dependent models) is the appropriate destructive action.
        problematic.destroy!
        {removed: true}
      when :ignore
        problem.update!(ignored: true)
        {ignored: true}
      else
        raise ArgumentError, "Unsupported action for MissingLibrary: #{action.inspect}"
      end
    end
  end
end
