# Wraps a Kaminari relation for restore mode (back-button scroll restoration).
# Exposes next_page for the sentinel turbo frame while delegating enumeration to the relation.
class ModelListRestoreWrapper
  include Enumerable

  attr_reader :relation, :restore_page, :per_page

  def initialize(relation, restore_page:, per_page:)
    @relation = relation
    @restore_page = restore_page
    @per_page = per_page
  end

  def next_page
    return nil if restore_page * per_page >= relation.total_count

    restore_page + 1
  end

  def each(&block)
    relation.each(&block)
  end

  def empty?
    relation.empty?
  end

  def any?
    relation.any?
  end

  def count
    relation.count
  end
end
