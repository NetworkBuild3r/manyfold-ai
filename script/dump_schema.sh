#!/usr/bin/env sh
# Generate db/schema.rb by running migrations against PostgreSQL in Docker.
# Run from project root. Requires Docker. Start DB first: docker compose up -d db redis
set -e
echo "Starting db and redis (if not already up)..."
docker compose up -d db redis || exit 1
echo "Waiting for PostgreSQL..."
sleep 3
echo "Running db:create db:migrate db:schema:dump in test container (writes to mounted repo)..."
docker compose --profile test run --rm -e SKIP_MIGRATIONS=1 test sh -c "bundle exec rails db:create db:migrate db:schema:dump" || exit 1
echo "Generated db/schema.rb. Commit it so the app container can start on a fresh database."
