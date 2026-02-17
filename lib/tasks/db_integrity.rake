# frozen_string_literal: true

# Uses raw SQL to avoid loading app models (Pundit, scopes) in a maintenance context.
namespace :db do
  desc "Check database integrity (orphaned records, dangling refs)"
  task integrity: :environment do
    conn = ActiveRecord::Base.connection
    checks = {}

    # 1. Orphaned model_files
    if conn.table_exists?(:model_files)
      result = conn.execute("SELECT COUNT(*) FROM model_files mf LEFT JOIN models m ON mf.model_id = m.id WHERE m.id IS NULL")
      checks["Orphaned model_files"] = result.first&.first || 0
    end

    # 2. Models with dangling creator_id
    if conn.table_exists?(:models)
      result = conn.execute("SELECT COUNT(*) FROM models m LEFT JOIN creators c ON m.creator_id = c.id WHERE m.creator_id IS NOT NULL AND c.id IS NULL")
      checks["Models with deleted creator"] = result.first&.first || 0
    end

    # 3. Models with dangling collection_id
    if conn.table_exists?(:models)
      result = conn.execute("SELECT COUNT(*) FROM models m LEFT JOIN collections c ON m.collection_id = c.id WHERE m.collection_id IS NOT NULL AND c.id IS NULL")
      checks["Models with deleted collection"] = result.first&.first || 0
    end

    # 4. Models with dangling library_id
    if conn.table_exists?(:models)
      result = conn.execute("SELECT COUNT(*) FROM models m LEFT JOIN libraries l ON m.library_id = l.id WHERE m.library_id IS NOT NULL AND l.id IS NULL")
      checks["Models with deleted library"] = result.first&.first || 0
    end

    # 5. Models with dangling preview_file_id
    if conn.table_exists?(:models) && conn.column_exists?(:models, :preview_file_id)
      result = conn.execute(
        "SELECT COUNT(*) FROM models WHERE preview_file_id IS NOT NULL AND preview_file_id NOT IN (SELECT id FROM model_files)"
      )
      checks["Models with deleted preview_file"] = result.first&.first || 0
    end

    # 6. Merge histories with dangling source_library_id
    if conn.table_exists?(:merge_histories) && conn.column_exists?(:merge_histories, :source_library_id)
      result = conn.execute(
        "SELECT COUNT(*) FROM merge_histories WHERE source_library_id IS NOT NULL AND source_library_id NOT IN (SELECT id FROM libraries)"
      )
      checks["Merge histories with deleted source library"] = result.first&.first || 0
    end

    # 7. Merge histories with dangling target_model_id
    if conn.table_exists?(:merge_histories)
      result = conn.execute(
        "SELECT COUNT(*) FROM merge_histories WHERE target_model_id NOT IN (SELECT id FROM models)"
      )
      checks["Merge histories with deleted target model"] = result.first&.first || 0
    end

    # 8. Orphaned memberships
    if conn.table_exists?(:memberships)
      result = conn.execute(
        "SELECT COUNT(*) FROM memberships WHERE group_id IS NOT NULL AND group_id NOT IN (SELECT id FROM groups)"
      )
      checks["Orphaned memberships (group)"] = result.first&.first || 0
      result = conn.execute(
        "SELECT COUNT(*) FROM memberships WHERE user_id IS NOT NULL AND user_id NOT IN (SELECT id FROM users)"
      )
      checks["Orphaned memberships (user)"] = result.first&.first || 0
    end

    # 9. Duplicate filenames within a model
    if conn.table_exists?(:model_files)
      result = conn.execute(
        "SELECT COUNT(*) FROM (SELECT model_id, filename FROM model_files GROUP BY model_id, filename HAVING COUNT(*) > 1) AS dups"
      )
      checks["Duplicate filenames"] = result.first&.first || 0
    end

    # 10. NULL digests
    if conn.table_exists?(:model_files)
      result = conn.execute("SELECT COUNT(*) FROM model_files WHERE digest IS NULL")
      checks["Files with NULL digest"] = result.first&.first || 0
    end

    checks.each do |label, count|
      status = count.zero? ? "OK" : "FOUND #{count}"
      puts "#{label}: #{status}"
    end
  end
end
