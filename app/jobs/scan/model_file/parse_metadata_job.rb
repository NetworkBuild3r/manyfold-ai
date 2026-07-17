class Scan::ModelFile::ParseMetadataJob < ApplicationJob
  queue_as :scan
  unique :until_executed

  # scan_batch_id: when set (library discovery), skip heavy AnalyseModelFileJob
  # (NFS digests / dups). Manual rescans pass nil and still enqueue analysis.
  def perform(file_id, scan_batch_id: nil)
    Current.set(scan_batch_id: scan_batch_id) do
      file = ModelFile.find(file_id)
      return unless file.exists_on_storage?

      # Attach shrine data if the row was created from a path scan without upload
      file.attach_existing_file! if file.attachment.blank?

      # Refresh shrine metadata (size, mime) without reading whole file body
      file.attachment_attacher.refresh_metadata!
      # Get metadata for specific types
      params = if file.is_image?
        image_metadata(file)
      elsif file.is_3d_model?
        model_metadata(file)
      end
      # Store updated data
      file.update!(params.compact) if params

      # Discovery mode: listable previews + size are enough. Digest/dup analysis
      # is expensive on multi-TB NFS and was the main secondary fan-out.
      # Deep path: single-model scan or upload still analyses immediately.
      defer_analysis = scan_batch_id.present? && ENV.fetch("SCAN_DEFER_ANALYSIS", "1") != "0"
      file.analyse_later unless defer_analysis
    end
  end

  def image_metadata(file)
    {
      previewable: true
    }
  end

  def model_metadata(file)
    {
      presupported: presupported?(file)
    }
  end

  def presupported?(file)
    elements = file.path_within_library.split(/[[:punct:]]|[[:space:]]/).map(&:downcase)
    elements.any? { |it| ModelFile::SUPPORT_KEYWORDS.include?(it) }
  end
end
