class MeshLoadError < StandardError
end

class MeshTooLargeError < StandardError
end

class Analysis::GeometricAnalysisJob < ApplicationJob
  queue_as :performance
  sidekiq_options retry: false
  unique :until_executed

  # Mittsu still requires a full in-memory string; cap size so one huge STL cannot OOM the worker.
  # Override with MAX_MESH_ANALYSIS_BYTES (bytes). Default 100 MiB.
  def self.max_mesh_bytes
    ENV.fetch("MAX_MESH_ANALYSIS_BYTES", 100.megabytes).to_i
  end

  def perform(file_id)
    # Get model
    file = ModelFile.find(file_id)
    return unless self.class.loader(file)
    return unless SiteSettings.analyse_manifold

    mesh = nil
    status[:step] = "jobs.analysis.geometric_analysis.loading_mesh" # i18n-tasks-use t('jobs.analysis.geometric_analysis.loading_mesh')
    mesh = self.class.load_mesh(file)
    if mesh
      status[:step] = "jobs.analysis.geometric_analysis.manifold_check" # i18n-tasks-use t('jobs.analysis.geometric_analysis.manifold_check')
      # Check for manifold mesh
      manifold = mesh.manifold?
      Problems::NonManifold.detect(file, should_exist: !manifold)
      # Temporarily disabled for release
      # # If the mesh is manifold, we can check if it's inside out
      # if manifold
      # i18n-tasks-use t('jobs.analysis.geometric_analysis.direction_check')
      # status[:step] = "jobs.analysis.geometric_analysis.direction_check"
      #   Problem.create_or_clear(
      #     file,
      #     :inside_out,
      #     !mesh.solid?
      #   )
      # end
    else
      raise MeshLoadError.new
    end
  rescue MeshTooLargeError => e
    Rails.logger.warn("[GeometricAnalysisJob] skipping file #{file_id}: #{e.message}")
  ensure
    # Drop large mesh graph before the next job reuses this Sidekiq process
    if mesh
      mesh = nil
      GC.start(full_mark: true, immediate_sweep: true)
    end
  end

  def self.loader(file)
    case file.extension.downcase
    when "stl"
      Mittsu::STLLoader
    when "obj"
      Mittsu::OBJLoader
    end
  end

  def self.load_mesh(file)
    size = file.size.to_i
    if size > max_mesh_bytes
      raise MeshTooLargeError, "file is #{size} bytes (limit #{max_mesh_bytes}); set MAX_MESH_ANALYSIS_BYTES to raise"
    end

    # TODO: stream into Mittsu when loaders accept IO (upstream)
    data = file.attachment.read
    begin
      loader(file)&.new&.parse(data)
    ensure
      data = nil
    end
  end
end
