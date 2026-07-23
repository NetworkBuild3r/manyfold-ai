# frozen_string_literal: true

# Free-text model search: scoped_search for exact/boolean syntax, plus Postgres
# fuzzy matching so typos like "rouge" still find "Rogue".
#
# Trigram similarity alone scores rouge↔rogue ~0.33 (below a useful threshold),
# so short tokens also use levenshtein against individual name/path words.
class Search::ModelSearchService
  # High-confidence trigram hits (exact-ish / close spellings of longer phrases).
  TRGM_THRESHOLD = 0.5
  # Short-token edit distance (transpositions like rouge/rogue need distance 2).
  MAX_LEVENSHTEIN = 2
  FUZZY_LIMIT = 200
  MIN_TERM_LENGTH = 3
  MAX_LEVENSHTEIN_TERM_LENGTH = 12

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
    return result unless term && DatabaseDetector.is_postgres? && fuzzy_extensions_ready?

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
    return nil unless DatabaseDetector.is_postgres? && fuzzy_extensions_ready?

    q.downcase
  end

  def fuzzy_match_ids(term)
    Model.where(fuzzy_where_sql, # rubocop:disable Pundit/UsePolicyScope
      term: term,
      trgm: TRGM_THRESHOLD,
      max_dist: MAX_LEVENSHTEIN,
      min_len: [term.length - 1, 3].max,
      max_len: term.length + 1)
      .limit(FUZZY_LIMIT)
      .pluck(:id)
  end

  def fuzzy_where_sql
    <<~SQL.squish
      (
        GREATEST(
          similarity(models.name, :term),
          word_similarity(:term, models.name),
          similarity(models.path, :term),
          word_similarity(:term, models.path)
        ) >= :trgm
      )
      OR (
        length(:term) <= #{MAX_LEVENSHTEIN_TERM_LENGTH}
        AND (
          EXISTS (
            SELECT 1
            FROM unnest(regexp_split_to_array(lower(models.name), '[^a-z0-9]+')) AS w
            WHERE left(w, 1) = left(:term, 1)
              AND length(w) BETWEEN :min_len AND :max_len
              AND levenshtein(w, :term) <= :max_dist
          )
          OR EXISTS (
            SELECT 1
            FROM unnest(regexp_split_to_array(lower(models.path), '[^a-z0-9]+')) AS w
            WHERE left(w, 1) = left(:term, 1)
              AND length(w) BETWEEN :min_len AND :max_len
              AND levenshtein(w, :term) <= :max_dist
          )
        )
      )
    SQL
  end

  def rank_order_sql(term)
    quoted = ActiveRecord::Base.connection.quote(term)
    min_len = [term.length - 1, 3].max
    max_len = term.length + 1
    <<~SQL.squish
      GREATEST(
        similarity(models.name, #{quoted}),
        word_similarity(#{quoted}, models.name),
        similarity(models.path, #{quoted}),
        word_similarity(#{quoted}, models.path),
        CASE WHEN EXISTS (
          SELECT 1 FROM unnest(regexp_split_to_array(lower(models.name), '[^a-z0-9]+')) AS w
          WHERE left(w, 1) = left(#{quoted}, 1)
            AND length(w) BETWEEN #{min_len} AND #{max_len}
            AND levenshtein(w, #{quoted}) = 0
        ) THEN 1.0
        WHEN EXISTS (
          SELECT 1 FROM unnest(regexp_split_to_array(lower(models.name), '[^a-z0-9]+')) AS w
          WHERE left(w, 1) = left(#{quoted}, 1)
            AND length(w) BETWEEN #{min_len} AND #{max_len}
            AND levenshtein(w, #{quoted}) = 1
        ) THEN 0.85
        WHEN EXISTS (
          SELECT 1 FROM unnest(regexp_split_to_array(lower(models.name), '[^a-z0-9]+')) AS w
          WHERE left(w, 1) = left(#{quoted}, 1)
            AND length(w) BETWEEN #{min_len} AND #{max_len}
            AND levenshtein(w, #{quoted}) <= #{MAX_LEVENSHTEIN}
        ) THEN 0.7
        ELSE 0 END
      ) DESC,
      models.updated_at DESC
    SQL
  end

  def fuzzy_extensions_ready?
    return @fuzzy_extensions_ready if defined?(@fuzzy_extensions_ready)

    conn = ActiveRecord::Base.connection
    @fuzzy_extensions_ready = conn.extension_enabled?("pg_trgm") &&
      conn.extension_enabled?("fuzzystrmatch")
  rescue ActiveRecord::StatementInvalid, NoMethodError
    @fuzzy_extensions_ready = false
  end
end
