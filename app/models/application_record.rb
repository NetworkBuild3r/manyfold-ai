class ApplicationRecord < ActiveRecord::Base
  self.abstract_class = true

  # Shared by models/creators/collections Sortable "random" ordering.
  scope :in_random_order, -> { order(Arel.sql("RANDOM()")) }

  # Default find_param implementation
  # just the same as standard find()
  def self.find_param(param)
    find(param)
  end
end
