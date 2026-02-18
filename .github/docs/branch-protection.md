# Branch protection for `main`

Nothing should be merged into `main` without passing CI and (optionally) review. Configure this in GitHub; it is not stored in the repo.

## Where to configure

**GitHub → Repository → Settings → Code and automation → Branches → Branch protection rules.**

Add or edit a rule for branch name **`main`**.

## Recommended settings

| Setting | Recommendation | Why |
|--------|----------------|-----|
| **Require a pull request before merging** | ✅ Enabled | No direct push to `main`; all changes go through a PR. |
| **Require status checks to pass before merging** | ✅ Enabled | Blocks merge if CI fails. |
| **Require branches to be up to date before merging** | ✅ Enabled | Ensures the PR is tested against the latest `main`. |
| **Status checks that are required** | Add: **`lint`**, **`test`** | These are the job names from [`.github/workflows/ci.yml`](../workflows/ci.yml). Both must pass. |
| **Require conversation resolution before merging** | Optional | Prevents merging with open review threads. |
| **Do not allow bypassing the above settings** | ✅ For admins too (if desired) | Ensures even admins follow the same rules. |
| **Restrict who can push to matching branches** | Optional | Leave empty to allow any collaborator with write access to open PRs; restrict if you use CODEOWNERS or a small merge group. |

## Status check names

After the first successful run of the CI workflow on a PR, GitHub will list available checks. Select:

- **lint** (from the `lint` job in `ci.yml`)
- **test** (from the `test` job in `ci.yml`)

If you use a matrix (e.g. multiple DBs), you may see **test (postgresql)**, **test (mysql2)**, **test (sqlite3)**. Require all of them, or require the single **test** job if GitHub groups them.

## Quick checklist

- [ ] Branch protection rule exists for `main`
- [ ] “Require a pull request before merging” is on
- [ ] “Require status checks to pass” is on, with **lint** and **test** (and any matrix variants) selected
- [ ] “Require branches to be up to date before merging” is on
- [ ] No one can push directly to `main` without going through a protected PR

## Applying via GitHub CLI (optional)

If you use [GitHub CLI](https://cli.github.com/) and have admin rights:

```bash
gh api repos/NetworkBuild3r/manyfold-ai/branches/main/protection \
  -X PUT \
  -H "Accept: application/vnd.github+json" \
  -f required_status_checks='{"strict":true,"contexts":["lint","test"]}' \
  -f enforce_admins=true \
  -f required_pull_request_reviews='{"dismiss_stale_reviews":false,"require_code_owner_reviews":false,"required_approving_review_count":0}' \
  -f restrictions=null
```

Adjust `required_approving_review_count` or `required_pull_request_reviews` if you want mandatory reviews. The exact payload may vary by API version; see [GitHub Docs: Update branch protection](https://docs.github.com/rest/branches/branches#update-branch-protection).
