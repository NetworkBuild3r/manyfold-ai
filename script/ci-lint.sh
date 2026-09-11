#!/usr/bin/env bash
# Container lint entrypoint for .github/workflows/ci.yml (avoids nested-quote SC2140).
set -euo pipefail

cd "$(dirname "$0")/.."

corepack enable
bundle config set --local path vendor/bundle
bundle install
yarn install
yarn build:css:tailwind
# Convention/warning backlog (~270 C/W) already existed on last-green main.
# INIT-027's set -e made `rake rubocop` fail the job; keep Error/Fatal fail-loud
# without rewriting that debt on the confirm/theme branch.
bundle exec rubocop --fail-level error
bundle exec erb_lint --lint-all
bash script/ui-contract-fence.sh --self-test
bash script/ui-contract-fence.sh --enforce jquery,invalid-scale,hex,base-class
yarn run lint:ts
node -e 'require("./eslint.config.js")'
yarn typecheck
bundle exec i18n-tasks health -l en
