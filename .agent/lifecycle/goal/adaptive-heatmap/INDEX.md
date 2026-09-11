# Adaptive Activity Heatmap

Status: Complete

## Outcome

Make the contribution heatmap use its available panel efficiently while
preserving calendar-week structure and exposing the activity represented by
each day.

## Acceptance

- Heatmap cells scale with the available panel instead of using a fixed size.
- Longer date ranges wrap into labeled calendar bands when that better fits
  the panel.
- Every requested day is represented exactly once.
- Activity intensity remains distinguishable when a few peak days dominate.
- Hovering a cell reveals its date and exact activity count.
- A populated screenshot verifies the final layout.

## Coordination

The GitHub checkout has no safely usable repository issue service in the
current environment, so this is the PAF lifecycle fallback for this outcome.

## Validation

- Synthetic 30-, 180-, and 365-day layout checks confirm every requested day
  is drawn exactly once and every cell remains inside the canvas.
- At the normal window size, cells scale to 33 px for 30 days and 16 px for
  180 days; a 365-day history wraps into two balanced calendar bands.
- Programmatic pointer checks confirm hover selection, exact date/count text,
  and hover cleanup.
- A live SSH-authenticated fetch for `Me (@tempris)` returned 30 days and 3,340
  activities for the final screenshot. A separate full 180-day validation
  returned all 180 daily rows and 5,384 activities.
- The final screenshot is fully painted and shows the adaptive short-range
  layout with centered month-span headers, date range, weekday labels, and
  intensity legend.
- A subsequent full-span SSH-authenticated capture renders all 180 days from
  March 16 through September 11 in bounds, using 17 px cells with independently
  scaled date, month, weekday, and legend labels. The live fetch returned 5,402
  activities for `Me (@tempris)` at capture time.
- The chart now resolves metric-driven grid changes before calculating canvas
  coordinates. A settled 180-day refetch verified unique consecutive dates and
  exact equality between all fetched and rendered daily counts; the corrected
  5,408-activity screenshot has no repeated right-edge segment.
- A plain `python gitea-activity-chart.py` launch remained open and responsive;
  the README launch command now uses the repository's actual hyphenated name.
- Python compilation and `git diff --check` pass.
