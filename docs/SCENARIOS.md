# Scenarios

Scenarios live in `scenarios/*.yaml`.

## Event types

### 1) set_param

Change a PX4 parameter mid-flight.

```yaml
- at_s: 20
  type: set_param
  name: SIM_BAT_MIN_PCT
  value: 5
```

### 2) inject_failure

Inject a fault using MAVSDK's Failure plugin.

```yaml
- at_s: 20
  type: inject_failure
  unit: gps
  failure: off
  instance: 0
```

Supported `failure` values include: `ok`, `off`, `stuck`, `garbage`, `wrong`, `slow`, `delayed`, `intermittent`.

## Adding scenarios safely

Keep them deterministic:
- Use **short timeouts**
- Prefer **simple event timelines**
- Gate on **simple metrics**
