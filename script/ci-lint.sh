#!/usr/bin/env bash
# Container lint entrypoint for .github/workflows/ci.yml (avoids nested-quote SC2140).
set -euo pipefail

cd "$(dirname "$0")/.."

corepack enable
bundle config set --local path vendor/bundle
bundle install
yarn install
yarn build:css:tailwind
bundle exec rake rubocop
bundle exec erb_lint --lint-all
bash script/ui-contract-fence.sh --self-test
bash script/ui-contract-fence.sh --enforce jquery,invalid-scale,hex,base-class
yarn run lint:ts
node -e 'require("./eslint.config.js")'
yarn typecheck
bundle exec i18n-tasks health -l en
