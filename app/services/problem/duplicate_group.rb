# frozen_string_literal: true

# One Problems-list row per identical-file digest, not per Problem record.
# A digest with three copies is one group: Merge folds models, Delete drops extras.
class Problem::DuplicateGroup
  def self.representative_ids(problem_query)
    scoped = problem_query.except(:includes, :preload, :eager_load, :order, :select)
    digest_reps = scoped.where(problematic_type: "ModelFile")
      .joins(file_join)
      .where.not(model_files: {digest: [nil, ""]})
      .group("model_files.digest")
      .pluck(Arel.sql("MIN(problems.id)"))
    digest_reps + leftover_ids(scoped, digest_reps)
  end

  def self.recoverable_bytes(problem_query, file_scope)
    file_ids = problem_query.except(:includes, :preload, :eager_load, :order, :select)
      .where(problematic_type: "ModelFile")
      .select(:problematic_id)
    digests = file_scope.where(id: file_ids).where.not(digest: [nil, ""]).distinct.pluck(:digest)
    return 0 if digests.empty?

    file_scope.where(digest: digests).pluck(:digest, :size).group_by(&:first).sum { |_digest, rows|
      sizes = rows.map { |(_, size)| size.to_i }
      extra = sizes.sum - sizes.max
      extra.positive? ? extra : 0
    }
  end

  def self.file_join
    "INNER JOIN model_files ON model_files.id = problems.problematic_id AND problems.problematic_type = 'ModelFile'"
  end
  private_class_method :file_join

  def self.leftover_ids(scoped, _digest_reps)
    blank = scoped.where(problematic_type: "ModelFile")
      .joins(file_join)
      .where(model_files: {digest: [nil, ""]})
      .pluck(:id)
    other_types = scoped.where.not(problematic_type: "ModelFile").pluck(:id)
    blank + other_types
  end
  private_class_method :leftover_ids
end
