# frozen_string_literal: true

module Problems
  class Base
    include Rails.application.routes.url_helpers

    class << self
      # Subclasses implement: return truthy if the problem exists for the given problematic.
      # They should call Problem.create_or_clear(problematic, category, should_exist, options).
      def detect(problematic)
        raise NotImplementedError, "#{name}.detect(problematic) must be implemented"
      end
    end

    # Subclasses implement: perform the resolution, return a result hash
    # e.g. { removed: true } or { redirect: url }. No HTTP in the class.
    def resolve!(problem, action:)
      raise NotImplementedError, "#{self.class.name}#resolve!(problem, action:) must be implemented"
    end
  end
end
