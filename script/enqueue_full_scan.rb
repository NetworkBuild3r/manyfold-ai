lib = Library.find_by(path: "/libraries/prints") || Library.first
abort("No library found") unless lib

puts "Library id=#{lib.id} name=#{lib.name} path=#{lib.path}"
puts "Models before: #{Model.count}"

# Preferred public API used by the UI
if lib.respond_to?(:detect_filesystem_changes_later)
  lib.detect_filesystem_changes_later
  puts "Enqueued detect_filesystem_changes_later"
elsif defined?(Scan::Library::DetectFilesystemChangesJob)
  Scan::Library::DetectFilesystemChangesJob.perform_later(lib.id)
  puts "Enqueued Scan::Library::DetectFilesystemChangesJob"
else
  abort "No scan entrypoint found"
end

puts "Models after enqueue: #{Model.count}"
puts "Sidekiq stats: #{Sidekiq::Stats.new.inspect rescue 'n/a'}"
