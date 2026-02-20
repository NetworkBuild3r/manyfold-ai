# frozen_string_literal: true

module Problems
  class Registry
    class << self
      # Register a category class. Optionally pass problematic_type for category+type-specific handlers.
      def register(category, klass, problematic_type = nil)
        key = problematic_type ? "#{category}/#{problematic_type}" : category.to_sym
        store[key] = klass
      end

      # Look up class for category (and optional problematic_type). Type-specific registration takes precedence.
      def for(category, problematic_type = nil)
        key = (problematic_type.presence && store.key?("#{category}/#{problematic_type}")) ? "#{category}/#{problematic_type}" : category.to_sym
        store[key] or raise KeyError, "No problem class registered for category: #{category.inspect}"
      end

      def registered?(category, problematic_type = nil)
        return true if store.key?(category.to_sym)
        problematic_type.presence && store.key?("#{category}/#{problematic_type}")
      end

      def store
        @store ||= {}
      end
    end
  end
end
