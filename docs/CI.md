# CI

GitHub Actions runs a small suite:

- baseline
- low battery

and uploads `runs/` as an artifact on every run.

Why no GPU? Because regression tests should be **portable** and **repeatable**.
GPU-only tests can be added as scheduled jobs later.
