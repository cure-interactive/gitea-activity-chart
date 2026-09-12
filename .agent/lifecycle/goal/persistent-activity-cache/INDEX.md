# Persistent Activity Cache

Status: Complete

## Outcome

Reuse previously fetched activity across application launches while giving the
user an explicit, safe way to discard cached results.

## Acceptance

- Successful activity fetches are persisted outside version control.
- Cache identity includes server, API path, authenticated viewer, target user,
  exact date range, and activity filter.
- Valid cached activity loads automatically after startup identity discovery.
- `Fetch Activity` reuses an exact cache match without network requests.
- `Clear Cache` removes all persisted and in-memory cache entries without
  clearing the currently displayed chart.
- Invalid cache content is ignored safely.

## Coordination

The repository uses a GitHub remote and no safely usable repository issue
service is available in the current environment, so this is the PAF lifecycle
fallback for this outcome.

## Validation

- Cache round-trip validation preserves complete daily series and rejects
  malformed, negative, incomplete, or non-consecutive entries.
- Cache keys distinguish server, API path, authenticated viewer, target user,
  exact date range, and performed-by filtering without storing credentials.
- Startup identity simulation loads a complete cached chart automatically.
- Incremental-fetch validation reuses two cached days and requests only the one
  missing day.
- Clear-cache validation removes the persisted file and all in-memory entries
  while preserving the currently displayed results.
- A live SSH-authenticated 180-day run for `tempris` loaded the saved chart,
  reused 179 days, fetched only today, and persisted the refreshed 5,431-event
  result.
- The cache-enabled application was relaunched through the Windows Python 3.14
  association fallback and remained responsive under Python 3.12.
- Python compilation, heatmap regression checks, and `git diff --check` pass.
