class ApplicationRecord < ActiveRecord::Base
  self.abstract_class = true

  # Shared by models/creators/collections Sortable "random" ordering.
  # Pass seed: for stable pagination (same shuffle across OFFSET pages).
  # Without seed, each query re-rolls via PostgreSQL RANDOM().
  scope :in_random_order, ->(seed: nil) {
    if seed.present?
      order(Arel.sql(sanitize_sql_array(["md5(#{connection.quote_table_name(table_name)}.id::text || ?) ASC", seed.to_s])))
    else
      order(Arel.sql("RANDOM()"))
    end
  }

  # Default find_param implementation
  # just the same as standard find()
  def self.find_param(param)
    find(param)
  end
end
