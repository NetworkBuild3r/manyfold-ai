# frozen_string_literal: true

module Problems
  # Handles resolution for categories not yet migrated to a dedicated class.
  # Returns result hashes so the controller can interpret redirect/removed.
  class LegacyResolver
    include Rails.application.routes.url_helpers

    def self.resolve(problem, action: nil)
      new.resolve(problem, action: action)
    end

    def resolve(problem, action: nil)
      strategy = action || problem.resolution_strategy
      case strategy
      when :show then { redirect: show_redirect_url(problem) }
      when :edit then { redirect: edit_redirect_url(problem) }
      when :destroy
        problematic = problem.problematic
        problem.destroy!
        case problem.problematic_type
        when "Model", "ModelFile"
          problematic.delete_from_disk_and_destroy
        else
          raise NotImplementedError
        end
        { removed: true }
      when :merge
        case problem.problematic_type
        when "Model"
          problem.update!(state: :resolving, in_progress: true)
          problem.problematic.merge!(problem.problematic.contained_models)
        else
          raise NotImplementedError
        end
        { removed: true }
      when :upload
        { redirect: model_path(problem.problematic, anchor: "upload-form") }
      when :convert
        problem.update!(state: :resolving, in_progress: true)
        problem.problematic.convert_later :threemf
        { in_progress: true }
      when :organize
        problem.update!(state: :resolving, in_progress: true)
        problem.problematic.organize_later(delay: 0)
        { in_progress: true }
      when :ignore
        problem.update!(ignored: true)
        { ignored: true }
      else
        raise NotImplementedError, "No resolution for #{strategy}"
      end
    end

    private

    def show_redirect_url(problem)
      case problem.problematic_type
      when "Model" then model_path(problem.problematic)
      when "ModelFile" then model_model_file_path(problem.problematic.model, problem.problematic)
      else raise NotImplementedError
      end
    end

    def edit_redirect_url(problem)
      case problem.problematic_type
      when "Library" then edit_library_path(problem.problematic)
      when "Model" then edit_model_path(problem.problematic)
      when "ModelFile" then edit_model_model_file_path(problem.problematic.model, problem.problematic)
      when "Link" then edit_model_path(problem.problematic.linkable)
      else raise NotImplementedError
      end
    end
  end
end
