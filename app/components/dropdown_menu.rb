# frozen_string_literal: true

# Shared dropdown panel styling for Stimulus dropdown controller.
# Use .panel_class(align:, direction:) for the menu ul; render trigger and content in your component.
class Components::DropdownMenu < Components::Base
  PANEL_CLASS_BASE = "absolute min-w-[10rem] py-1 bg-white dark:bg-secondary-800 rounded-lg shadow-lg border border-secondary-200 dark:border-secondary-600 z-50".freeze

  def self.panel_class(align: :right, direction: :down)
    base = PANEL_CLASS_BASE.dup
    base += " right-0" if align == :right
    base += " left-0" if align == :left
    base += " mt-1" if direction == :down
    base += " bottom-full mb-1" if direction == :up
    base
  end
end
