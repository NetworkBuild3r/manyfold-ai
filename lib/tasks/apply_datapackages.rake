# frozen_string_literal: true

namespace :manyfold do
  desc "Apply on-disk datapackage.json metadata to scanned models " \
       "(creator, tags, caption, notes, links, preview). " \
       "DRY_RUN=1 to preview. FORCE=1 to overwrite existing fields. " \
       "LIBRARY_ID= optional. LIMIT=0 means all."
  task apply_datapackages: :environment do
    dry_run = ENV.fetch("DRY_RUN", "0").match?(/\A(1|true|yes)\z/i)
    force = ENV.fetch("FORCE", "0").match?(/\A(1|true|yes)\z/i)
    limit = Integer(ENV.fetch("LIMIT", "0"))
    library_id = ENV["LIBRARY_ID"].presence&.to_i

    resolve_creator = lambda do |attrs|
      return nil unless attrs.is_a?(Hash)

      if attrs[:id].present?
        return Creator.find_by(id: attrs[:id])
      end

      name = attrs[:name].presence
      return nil if name.blank?

      existing = Creator.find_by("LOWER(name) = ?", name.downcase) ||
        Creator.find_by(slug: name.parameterize)
      return existing if existing
      return Creator.new(name: name, slug: name.parameterize) if dry_run

      creator = Creator.create!(name: name, slug: name.parameterize)
      Array(attrs[:links_attributes]).each do |link|
        url = link[:url].presence
        next if url.blank?

        creator.links.find_or_create_by!(url: url)
      end
      creator
    end

    scope = Model.all # rubocop:disable Pundit/UsePolicyScope -- operator rake
    scope = scope.where(library_id: library_id) if library_id
    scope = scope.order(:id)
    scope = scope.limit(limit) if limit.positive?

    updated = 0
    skipped = 0
    missing = 0
    errors = 0

    scope.find_each do |model|
      next if model.remote?

      path = begin
        File.join(model.library.path, model.path, "datapackage.json")
      rescue StandardError
        nil
      end
      unless path && File.file?(path)
        missing += 1
        next
      end

      begin
        data = JSON.parse(File.read(path))
        parsed = DataPackage::ModelDeserializer.new(data).deserialize
        changes = {}

        if parsed[:name].present? && (force || model.name.blank?)
          changes[:name] = parsed[:name]
        end
        if parsed[:caption].present? && (force || model.caption.blank?)
          changes[:caption] = parsed[:caption]
        end
        if parsed[:notes].present? && (force || model.notes.blank?)
          changes[:notes] = parsed[:notes]
        end
        if !parsed[:sensitive].nil? && (force || model.sensitive.nil?)
          changes[:sensitive] = parsed[:sensitive]
        end

        if parsed[:tag_list].present?
          merged = (model.tag_list.map(&:to_s) + Array(parsed[:tag_list]).map(&:to_s)).map(&:downcase).uniq
          if force || (merged - model.tag_list.map { |t| t.to_s.downcase }).any?
            changes[:tag_list] = merged
          end
        end

        if parsed[:creator].is_a?(Hash) && (force || model.creator_id.nil?)
          creator = resolve_creator.call(parsed[:creator])
          changes[:creator] = creator if creator
        end

        if parsed[:preview_file].present? && (force || model.preview_file_id.nil?)
          filename = File.basename(parsed[:preview_file].to_s)
          file = model.model_files.find_by(filename: filename) ||
            model.model_files.find_by(filename_lower: filename.downcase)
          changes[:preview_file] = file if file
        end

        link_urls = Array(parsed[:links_attributes]).filter_map { |it| it[:url].presence }
        new_links = link_urls.reject { |url| model.links.exists?(url: url) }

        if changes.empty? && new_links.empty?
          skipped += 1
          next
        end

        puts "[#{model.id}] #{model.path} changes=#{changes.keys} new_links=#{new_links.size}"
        unless dry_run
          model.update!(changes) if changes.any?
          new_links.each { |url| model.links.find_or_create_by!(url: url) }
        end
        updated += 1
      rescue StandardError => e
        errors += 1
        warn "ERROR model=#{model.id} path=#{model.path}: #{e.class}: #{e.message}"
      end
    end

    puts({
      dry_run: dry_run,
      force: force,
      updated: updated,
      skipped: skipped,
      missing_datapackage: missing,
      errors: errors
    }.inspect)
  end
end
