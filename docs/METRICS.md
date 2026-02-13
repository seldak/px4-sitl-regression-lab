# Metrics

The extractor (`px4_lab/metrics/extract.py`) reads the ULog and computes:

- `flight_time_s`
- `max_speed_m_s`
- `max_horiz_error_m`
- `rms_horiz_error_m`
- `max_tilt_deg`
- `min_battery_remaining`
- `nav_state_histogram` (best effort)

These are intentionally “portfolio friendly”:
they show you can **turn logs into objective performance gates**.
