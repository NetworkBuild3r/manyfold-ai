#!/bin/bash
cd /mnt/c/Users/BrianNelson/Projects/manyfold-ai
echo "=== job file head ==="
docker compose exec -T worker head -8 /usr/src/app/app/jobs/scan/library/detect_filesystem_changes_job.rb
echo "=== worker procs ==="
docker compose exec -T worker ps aux
for i in $(seq 1 15); do
  echo "=== sample $i $(date -Is) ==="
  docker compose logs worker --since 2m 2>/dev/null | grep -iE 'scan|new_models|scanned_files|CreateModel|ERROR|done|DetectFilesystem' | tail -10
  docker compose exec -T web bundle exec rails runner 'puts "Models=#{Model.count} Files=#{ModelFile.count} Enqueued=#{Sidekiq::Stats.new.enqueued} Queues=#{Sidekiq::Stats.new.queues.inspect}"' 2>/dev/null | grep Models=
  busy=$(docker compose exec -T worker ps aux 2>/dev/null | grep sidekiq | head -1)
  echo "sidekiq: $busy"
  sleep 25
done
