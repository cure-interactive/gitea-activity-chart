# Faster Activity Fetch

Status: Complete

## Objective

Reduce live Gitea activity-fetch latency without changing the daily activity
counts shown by the application.

## Evidence and acceptance

- Benchmark candidate fetch paths against the existing verified 180-day data.
- Record request count, elapsed time, and exact per-day comparison results.
- Adopt only a path that preserves the requested activity semantics, with a
  compatible fallback for servers that do not support it.
- Run focused automated tests for the chosen path and existing cache behavior.

## Outcome

- Each SSH HTTP signature now covers a unique `X-Request-Id`, preserving replay
  protection without forcing successive requests into different whole seconds.
- Missing dates are fetched through six concurrent workers; pagination within
  each date remains unchanged.
- The aggregate heatmap endpoint was rejected as the primary data source after
  it differed from the activity feed on two historical dates.

## Validation

- The aggregate endpoint returned 2,400 buckets in 0.056 seconds, but only 177
  of 179 historical daily counts matched the verified activity-feed baseline.
- The production parallel feed path made 256 signed requests for 179 days in
  6.17 seconds and matched all 179 daily counts and the complete 5,380-event
  total exactly. The former timestamp-throttled signing path required at least
  one second between those requests.
- A 12-day rapid sequential sample made 45 signed requests in 3.975 seconds and
  matched all 12 expected daily counts.
- A controlled 30-day benchmark held the expected 86-request workload and data
  constant: one, two, four, six, and eight workers completed in 6.912, 3.778,
  2.301, 2.244, and 2.485 seconds respectively. Six was the fastest measured
  setting; all five runs matched every expected daily count. The six- and
  eight-worker runs each made two extra signed requests while transparently
  recovering from one transient authentication retry.
- Automated tests cover unique rapid signatures, actual concurrent execution,
  exact result preservation, and progress reporting.
- Existing persistent-cache tests and Python compilation pass.

## Coordination

The repository uses a GitHub remote and no safely usable repository issue
service is available in the current environment, so this is the PAF lifecycle
fallback for this outcome.
