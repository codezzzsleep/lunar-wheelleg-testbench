# Classification correction — old ref comparison (a34a55b90)

The previous ref run reported `physical_failure` at 40.6 s for the L2 executions. That
duration matches the old EpisodeRunner default `max_steps=2000` at 50 Hz (40 s) plus the
final step, i.e. **execution truncation by the step cap**, not a physical failure.

- Old records are kept unchanged.
- Correct classification: `truncated_by_cap`, not `physical_failure`.
- The runner now receives `max_steps = max_seconds * control_hz` (6000 for 120 s) and rows carry
  `step_cap` / `truncated_by_cap`; a re-run is required before any formal cost statement.
