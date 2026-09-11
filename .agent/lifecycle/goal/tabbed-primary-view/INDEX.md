# Tabbed Primary View

Status: Complete

## Outcome

Keep activity exploration as the primary view, move connection and
authentication configuration into a second tab, and verify the result with the
authenticated user's own activity selected.

## Acceptance

- `Activity` is the first and initially selected tab.
- `Configuration` is the second tab and owns connection, authentication, and
  configuration-save controls.
- User selection and activity query controls remain on the primary tab.
- The current authenticated identity is selected for the validation fetch.
- A clean populated screenshot verifies the final layout.

## Coordination

The GitHub checkout has no safely usable repository issue service in the
current environment, so this is the PAF lifecycle fallback for the new outcome.

## Validation

- Runtime inspection confirms the tab order is `Activity`, then
  `Configuration`, with `Activity` selected initially.
- Configuration controls render on the second tab and activity controls render
  on the first.
- A live SSH-authenticated 30-day fetch completed for `Me (@tempris)` with
  3,421 activity events.
- The final settled-frame screenshot contains no unpainted white capture area.
- Windows double-click startup was verified from the machine's Python 3.14 file
  association: the bootstrap selected dependency-ready Python 3.12 via
  `pythonw`, and the resulting application window remained responsive.
- Python compilation and `git diff --check` pass.
