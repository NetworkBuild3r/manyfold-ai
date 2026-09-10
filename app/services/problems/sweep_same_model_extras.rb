# frozen_string_literal: true

# Extra copies of the same bytes on one model are leftover merge debris.
# Keep the oldest file, drop the rest, then re-detect so Problems clears.
class Problems::SweepSameModelExtras
  Result = Struct.new(:collapsed, :retracted, keyword_init: true)

  def self.call(model: nil)
    new(model: model).call
  end

  def initialize(model: nil)
    @model = model
  end

  def call
    collapsed = collapse_extras!
    retracted = refresh_problems!
    Result.new(collapsed: collapsed, retracted: retracted)
  end

  private

  def collapse_extras!
    count = 0
    grouped_copies.each_value do |copies|
      next if copies.size < 2

      copies.sort_by(&:id).drop(1).each do |extra|
        extra.delete_from_disk_and_destroy
        count += 1
      end
    end
    count
  end

  def grouped_copies
    candidate_files.to_a
      .select { |file| file.digest.present? && (file.duplicate_geometry? || file.is_archive?) }
      .group_by { |file| [file.model_id, file.digest] }
  end

  def candidate_files
    if @model
      @model.model_files.where.not(digest: [nil, ""])
    else
      digests = problem_digests
      return ModelFile.none if digests.empty?

      ModelFile.where(digest: digests)
    end
  end

  def problem_digests
    ids = Problem.where(category: "duplicate", problematic_type: "ModelFile").pluck(:problematic_id)
    ModelFile.where(id: ids).where.not(digest: [nil, ""]).distinct.pluck(:digest)
  end

  def refresh_problems!
    retracted = 0
    refresh_scope.find_each do |file|
      next unless file.persisted?

      existed = file.problems.exists?(category: :duplicate)
      Problems::Duplicate.detect(file)
      retracted += 1 if existed && !file.problems.exists?(category: :duplicate)
    end
    retracted
  end

  def refresh_scope
    if @model
      @model.model_files.reload
    else
      ids = Problem.where(category: "duplicate", problematic_type: "ModelFile").pluck(:problematic_id)
      ModelFile.where(id: ids)
    end
  end
end
