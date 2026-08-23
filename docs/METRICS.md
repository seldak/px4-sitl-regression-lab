# Metrics

The extractor (`px4_lab/metrics/extract.py`) reads the ULog and computes:

- `flight_time_s`
- `max_speed_m_s`
- `max_horiz_error_m`
- `rms_horiz_error_m`
- `max_tilt_deg`
- `min_battery_remaining`
- `nav_state_histogram` (best effort)

These metrics turn flight logs into objective performance gates.

## Trust layer

Every run selects one structured flight window that is shared by metric extraction and
plot generation. High-rate local-position movement and altitude are preferred; debounced
land-detector state is a fallback. Selecting the whole ULog is explicitly untrusted and
cannot pass a scenario.

The report records the window source, duration, sample count, analyzed fraction of the
ULog, diagnostics, horizontal-error provenance, and waypoint coverage. A run also fails
when runtime integrity is broken (mission did not start/land, timeout, runtime exceptions,
or configured events did not execute).

Scenario thresholds can add trust gates:

```yaml
thresholds:
  min_flight_time_s: 30
  min_waypoint_completion_ratio: 0.75
  waypoint_radius_m: 8
  min_window_samples: 500
  require_mission_finished: true
```
