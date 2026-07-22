# frozen_string_literal: true

namespace :manyfold do
  desc "List archives and enqueue entry previews. MODEL_ID=public_id or all"
  task scan_archives: :environment do
    scope = if ENV["MODEL_ID"].present?
      Model.where(public_id: ENV["MODEL_ID"])
    elsif ARGV[1].present? && ARGV[1] != "all"
      Model.where(public_id: ARGV[1])
    else
      Model.all
    end

    count = 0
    scope.find_each do |model|
      model.model_files.find_each do |file|
        next unless file.is_archive?
        file.scan_archive_later
        count += 1
        puts "queued ListArchiveJob for model=#{model.public_id} file=#{file.filename}"
      end
    end
    puts "queued #{count} archive scan(s)"
  end
end
