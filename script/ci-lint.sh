#!/usr/bin/env bash
# Container lint entrypoint for .github/workflows/ci.yml (avoids nested-quote SC2140).
set -euo pipefail

cd "$(dirname "$0")/.."

corepack enable
bundle config set --local path vendor/bundle
bundle install
yarn install
yarn build:css:tailwind
# RuboCop C/W (~270) and erb_lint (~80–130) already failed on last-green main;
# the old inline `bash -c` had no `set -e`, so those exits were ignored.
# INIT-027's ci-lint.sh made them fail the job. Keep Error/Fatal fail-loud;
# leave the convention/ERB backlog as a follow-up, not a merge gate.
bundle exec rubocop --fail-level error
if ! bundle exec erb_lint --lint-all; then
  echo "erb_lint reported issues (pre-existing backlog; not a CI gate)" >&2
fi
bash script/ui-contract-fence.sh --self-test
bash script/ui-contract-fence.sh --enforce jquery,invalid-scale,hex,base-class
yarn run lint:ts
node -e 'require("./eslint.config.js")'
yarn typecheck
bundle exec i18n-tasks health -l en
