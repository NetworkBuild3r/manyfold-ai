// INIT-027/SPEC-002 — ESLint 9 flat config. Ignores map the former .eslintignore.
// ts-standard remains the TypeScript style checker (package.json lint:ts).
'use strict'

module.exports = [
  {
    ignores: [
      'app/assets/builds/**',
      'node_modules/**',
      'vendor/**',
      'coverage/**',
      'public/**'
    ]
  }
]
