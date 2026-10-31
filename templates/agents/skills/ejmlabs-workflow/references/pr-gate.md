# The PR gate

Opening or updating a PR authorizes no CI spending by itself. Draft versus Ready
and maintainer permission do.

## Admission

| Who | How paid checks start |
| --- | --- |
| Maintainer author, same-repo, non-draft | Auto-admitted on open, push and Ready |
| Outsider or fork | Only when a current maintainer marks Ready |
| Draft PR | Never admitted |

Agents may mark a PR Ready (`gh pr ready N`) only when the user explicitly asks.
They must not do it unprompted.

## Labels

Exact label name equality only. Agents add these only when the user explicitly
asks.

| Label | Effect |
| --- | --- |
| `gate:approve` | Records a bot APPROVE for the current head, then removes the label |
| `gate:revoke` | Cancels admitted work and dismisses bot approvals for that head |

```sh
gh pr edit 41 --repo ejmlabs/ejmlabs --add-label gate:approve
gh pr edit 41 --repo ejmlabs/ejmlabs --add-label gate:revoke
```

Slash-command comments such as `/ready` or `/approve` are not admission or
approval signals.

## Rules

- Draft PRs spend nothing. Mark Ready when the work is ready for checks.
- A new commit needs a new admission. Push the final commit before asking the
  user to mark Ready or add `gate:approve`.
- Actions reruns cannot replay admission. To retry: convert to draft and Ready
  again, or push a new commit, or ask for `gate:revoke` then a fresh Ready.
- When `main` moves and the PR is behind, update the branch
  (`gh pr update-branch N`). That makes a new head commit.
- With strict up-to-date checks, land one PR per repository at a time. Every
  merge puts the others behind.

## Required statuses

**Quality** and **Repository standards**, plus one approving GitHub review
(`enforce_admins`). Read the PR's checks for the current set.

- Repository standards checks community files and versions against the pinned
  shared standard. Never edit synced files by hand; resync them from
  `ejmlabs/.github`.

## Limits

| Limit                   | Bound      |
| ----------------------- | ---------- |
| Changed files           | 200        |
| Added and deleted lines | 12,000     |
| Quality job             | 45 minutes |

Split larger work into a sequence of PRs that each pass alone.

## Merge

```sh
gh pr checks N --repo ejmlabs/REPO
gh pr merge N --repo ejmlabs/REPO --squash --match-head-commit FULL_SHA
```

Merge only when every check is green. Never merge as an administrator around a
failing or missing check.
