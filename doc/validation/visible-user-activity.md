# Visible User Activity

Status: Complete

## Outcome

Let the authenticated user discover every Gitea user visible to their account,
select or manually enter a username, and inspect that user's activity with
efficient repeat switching.

## Acceptance

- Visible-user discovery consumes every paginated search result.
- The current user appears first and user labels retain the canonical login.
- The selector is searchable/editable and supports manual usernames.
- Refresh is explicit and user discovery also runs after startup.
- Changing users never triggers an expensive activity fetch automatically.
- Previously fetched daily activity is reused from an in-memory query cache.
- The layout and populated states are verified without DPI-corrupted captures.

## Validation

- Live SSH-authenticated discovery returned six visible users with the current
  account first.
- A different visible user's 30-day activity fetched and rendered successfully.
- Focused checks passed for pagination, search filtering, display-to-login
  mapping, manual entry, cache reuse, logical geometry persistence, and the
  detached activity log.
- Both Python entry points compile and `git diff --check` passes.
- A clean DPI-safe screenshot verifies the final populated layout.
