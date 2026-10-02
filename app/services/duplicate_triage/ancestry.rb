# frozen_string_literal: true

require "pathname"

module DuplicateTriage
  # Same nesting test as Model#parents / merge eligibility: one model's
  # library path is a filesystem ancestor of the other. Pathname only — names
  # are never compared (INIT-031/SPEC-003, D-2).
  module Ancestry
    def self.nested?(left, right)
      return false if left.library_id != right.library_id

      ancestor_path?(left.path, right.path) || ancestor_path?(right.path, left.path)
    end

    def self.ancestor_path?(ancestor, descendant)
      return false if ancestor.blank? || descendant.blank?
      return false if ancestor == descendant

      ancestor_pathname = Pathname.new(ancestor)
      Pathname.new(descendant).ascend.drop(1).any? { |parent| parent == ancestor_pathname }
    end
    private_class_method :ancestor_path?
  end
end
