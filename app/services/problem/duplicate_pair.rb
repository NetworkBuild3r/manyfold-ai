# frozen_string_literal: true

# A duplicate Problem is always on one ModelFile. This object names the other
# copies (same digest) so the UI can say what Delete removes and whether Merge
# can fold two models together.
class Problem::DuplicatePair
  attr_reader :file, :model, :counterparts, :other_models

  def self.build(problem, files_by_digest = nil)
    file = problem.problematic
    return unless problem.category == "duplicate" && file.is_a?(ModelFile)

    others = if files_by_digest
      Array(files_by_digest[file.digest]).reject { |other| other.id == file.id }
    else
      file.duplicates.includes(:model).to_a
    end
    new(file: file, counterparts: others)
  end

  def self.map_for(problems, scoped_files)
    files = problems.filter_map { |problem|
      problem.problematic if problem.category == "duplicate" && problem.problematic.is_a?(ModelFile)
    }
    digests = files.filter_map(&:digest).uniq
    grouped = if digests.empty?
      {}
    else
      scoped_files.where(digest: digests).includes(:model).group_by(&:digest)
    end
    problems.each_with_object({}) do |problem, memo|
      pair = build(problem, grouped)
      memo[problem.id] = pair if pair
    end
  end

  def initialize(file:, counterparts:)
    @file = file
    @model = file.model
    @counterparts = Array(counterparts)
    @other_models = @counterparts.filter_map(&:model).uniq.reject { |other| other.id == @model.id }
  end

  def mergeable?
    other_models.any?
  end

  def same_model_copies
    counterparts.select { |other| other.model_id == file.model_id }
  end

  def primary_other_file
    counterparts.find { |other| other.model_id != file.model_id } || counterparts.first
  end

  def other_model_for(public_id)
    return other_models.first if public_id.blank?

    other_models.find { |other| other.public_id == public_id }
  end
end
