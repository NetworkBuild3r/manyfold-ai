# frozen_string_literal: true

# Free-text model search: scoped_search for exact/boolean syntax, plus a
# Postgres pg_trgm fuzzy fallback so typos like "rouge" still find "Rogue".
class Search::ModelSearchService
  # word_similarity("rouge", "Rogue (Marvel)") is typically ~0.5; keep a floor
  # that still catches one-letter swaps without flooding the result set.
  FUZZY_THRESHOLD = 0.35
  FUZZY_LIMIT = 100
  MIN_TERM_LENGTH = 3

  def initialize(scope)
    base = scope.includes("federails_actor")
    @scope = base.where("federails_actor.local": true).or(
      base.where("federails_actor.local": false, indexable: "yes")
    )
  end

  def search(query)
    term = simple_fuzzy_term(query)
    exact_ids = exact_match_ids(query)
    fuzzy_ids = term ? fuzzy_match_ids(term) : []
    ids = (exact_ids + fuzzy_ids).uniq
    return @scope.none if ids.empty?

    result = @scope.where(id: ids)
    return result unless term && DatabaseDetector.is_postgres? && pg_trgm_ready?

    result.order(Arel.sql(rank_order_sql(term)))
  end

  private

  def exact_match_ids(query)
    if DatabaseDetector.is_postgres?
      Model.select("DISTINCT ON (models.id) models.*") # rubocop:disable Pundit/UsePolicyScope
        .search_for(query)
        .pluck(:id) # rubocop:todo Rails/PluckInWhere
    else
      Model.search_for(query).distinct.pluck(:id) # rubocop:disable Pundit/UsePolicyScope
    end
  rescue ScopedSearch::QueryNotSupported
    []
  end

  # Bare single-token queries only — skip advanced scoped_search syntax.
  def simple_fuzzy_term(query)
    q = query.to_s.strip
    return nil if q.length < MIN_TERM_LENGTH
    return nil if q.match?(/[~=<>!()"]|\b(and|or|not)\b/i)
    return nil if q.include?(" ")
    return nil unless DatabaseDetector.is_postgres? && pg_trgm_ready?

    q
  end

  def fuzzy_match_ids(term)
    # word_similarity ranks the best matching word inside longer titles/paths.
    sql = <<~SQL.squish
      GREATEST(
        similarity(models.name, :term),
        word_similarity(:term, models.name),
        similarity(models.path, :term),
        word_similarity(:term, models.path)
      ) >= :threshold
    SQL
    Model.where(sql, term: term, threshold: FUZZY_THRESHOLD) # rubocop:disable Pundit/UsePolicyScope
      .limit(FUZZY_LIMIT)
      .pluck(:id)
  end

  def rank_order_sql(term)
    quoted = ActiveRecord::Base.connection.quote(term)
    <<~SQL.squish
      GREATEST(
        similarity(models.name, #{quoted}),
        word_similarity(#{quoted}, models.name),
        similarity(models.path, #{quoted}),
        word_similarity(#{quoted}, models.path)
      ) DESC,
      models.updated_at DESC
    SQL
  end

  def pg_trgm_ready?
    return @pg_trgm_ready if defined?(@pg_trgm_ready)

    @pg_trgm_ready = ActiveRecord::Base.connection.extension_enabled?("pg_trgm")
  rescue ActiveRecord::StatementInvalid, NoMethodError
    @pg_trgm_ready = false
  end
end
