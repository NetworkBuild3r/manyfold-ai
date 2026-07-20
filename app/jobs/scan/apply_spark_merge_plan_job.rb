# frozen_string_literal: true

# Consume spark-curate merges-pending.jsonl and call Model#merge!.
# Plans live on the library volume under .spark-curate/ (same PVC as spark-curate /library).
class Scan::ApplySparkMergePlanJob < ApplicationJob
  queue_as :default
  unique :until_executed, lock_ttl: 2.hours

  PENDING = "merges-pending.jsonl"
  APPLIED = "merges-applied.jsonl"
  FAILED = "merges-failed.jsonl"

  def perform(library_id: nil, dry_run: false, limit: 500)
    scope = Library.all
    scope = scope.where(id: library_id) if library_id.present?

    totals = {applied: 0, failed: 0, skipped: 0, dry_run: dry_run}
    scope.find_each do |library|
      next unless library.storage_service == "filesystem"
      next if library.path.blank?

      result = process_library(library, dry_run: dry_run, limit: limit - totals[:applied] - totals[:failed])
      totals[:applied] += result[:applied]
      totals[:failed] += result[:failed]
      totals[:skipped] += result[:skipped]
      break if (totals[:applied] + totals[:failed]) >= limit
    end

    Rails.logger.info("[scan] ApplySparkMergePlanJob #{totals.inspect}")
    totals
  end

  private

  def process_library(library, dry_run:, limit:)
    work = Pathname.new(library.path).join(".spark-curate")
    pending_path = work.join(PENDING)
    return {applied: 0, failed: 0, skipped: 0} unless pending_path.file?

    lines = pending_path.readlines(encoding: "UTF-8")
    return {applied: 0, failed: 0, skipped: 0} if lines.empty?

    remaining = []
    applied = failed = skipped = 0
    processed = 0

    lines.each do |line|
      line = line.strip
      if line.blank?
        skipped += 1
        next
      end

      if processed >= limit
        remaining << line
        next
      end

      begin
        rec = JSON.parse(line)
      rescue JSON::ParserError => e
        append_jsonl(work.join(FAILED), {"raw" => line, "error" => e.message})
        failed += 1
        processed += 1
        next
      end

      result = apply_record(library, rec, dry_run: dry_run)
      processed += 1
      case result[:status]
      when :applied
        append_jsonl(work.join(APPLIED), rec.merge("result" => result))
        applied += 1
      when :dry_run
        remaining << line
        skipped += 1
      when :skipped
        append_jsonl(work.join(FAILED), rec.merge("result" => result)) unless dry_run
        skipped += 1
        remaining << line if dry_run
      else
        append_jsonl(work.join(FAILED), rec.merge("result" => result))
        failed += 1
      end
    end

    unless dry_run
      if remaining.empty?
        pending_path.delete if pending_path.file?
      else
        pending_path.write(remaining.map { |l| l.end_with?("\n") ? l : "#{l}\n" }.join, encoding: "UTF-8")
      end
    end

    {applied: applied, failed: failed, skipped: skipped}
  end

  def apply_record(library, rec, dry_run:)
    path_a = rec["path_a"].to_s
    path_b = rec["path_b"].to_s
    target_key = rec["target"].to_s.downcase
    confidence = rec["confidence"].to_f

    if path_a.blank? || path_b.blank?
      return {status: :failed, error: "missing paths"}
    end
    if confidence < 0.80
      return {status: :skipped, error: "confidence below 0.80"}
    end

    model_a = library.models.find_by(path: path_a)
    model_b = library.models.find_by(path: path_b)
    if model_a.nil? || model_b.nil?
      return {
        status: :skipped,
        error: "model not found",
        found_a: model_a.present?,
        found_b: model_b.present?
      }
    end

    unless model_a.exists_on_storage? && model_b.exists_on_storage?
      return {status: :skipped, error: "one or both folders missing on storage"}
    end

    target, source = if target_key == "b"
      [model_b, model_a]
    else
      [model_a, model_b]
    end

    if dry_run
      return {
        status: :dry_run,
        target_path: target.path,
        source_path: source.path,
        target_id: target.id,
        source_id: source.id
      }
    end

    target.merge!(source)
    {
      status: :applied,
      target_path: target.path,
      source_path: source.path,
      target_id: target.id
    }
  rescue => e
    {status: :failed, error: "#{e.class}: #{e.message}"}
  end

  def append_jsonl(path, hash)
    path.dirname.mkpath
    path.open("a") { |fh| fh.puts(JSON.generate(hash)) }
  end
end
