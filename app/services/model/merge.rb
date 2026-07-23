# frozen_string_literal: true

# Application-layer merge of one or more source models into a target.
class Model::Merge
  def self.call(target, *sources)
    new(target).call(*sources)
  end

  def initialize(target)
    @target = target
  end

  def call(*models)
    models = models[0] if models.length == 1 && models[0].is_a?(Enumerable)

    models.each do |other|
      ActiveRecord::Base.transaction do
        path_prefix = @target.compute_merge_prefix(other)

        moved_files = []
        other.model_files.to_a.each do |file|
          source_filename = file.filename
          result = @target.adopt_file(file, path_prefix: path_prefix)

          moved_files << {
            id: file.id,
            source_filename: source_filename,
            merged_filename: (result[:status] == :adopted) ? file.filename : nil,
            deduplicated: result[:status] == :deduplicated,
            existing_file_id: result[:existing_file_id]
          }
        end

        MergeHistory.create!(
          target_model: @target,
          source_library_id: other.library_id,
          source_path: other.path,
          source_name: other.name,
          path_prefix: path_prefix,
          source_metadata: {
            creator_id: other.creator_id,
            collection_id: other.collection_id,
            license: other.license,
            caption: other.caption,
            notes: other.notes,
            sensitive: other.sensitive,
            tag_list: other.tag_list,
            links: other.links.map(&:url),
            preview_filename: other.preview_file&.filename
          },
          moved_files: moved_files
        )

        # Merge metadata (target wins for single-value fields)
        @target.creator ||= other.creator
        @target.collection ||= other.collection
        @target.license ||= other.license
        @target.caption ||= other.caption
        @target.notes ||= other.notes
        @target.sensitive ||= other.sensitive
        @target.tag_list.add(*other.tag_list)
        @target.links_attributes = other.links.map { |it| {url: it.url} }
        @target.save!

        other.reload
        other.destroy!
      end
      @target.check_for_problems_later
    end
  end
end
