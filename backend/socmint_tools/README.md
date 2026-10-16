# socmint_tools

Public-data OSINT collectors vendored from
[SOCMIntelligence](https://github.com/emrekybs/SOCMIntelligence) (Emre Kybs).
Each script is a standalone CLI that prints one JSON object; Veiled Eye runs them in a
subprocess through `factories/socmint_runner.py` (thread/process safe) and
converts the output into Veiled Eye's positional result format in
`modules/<name>/<name>_tasks.py`.

Only change from upstream: `snap_osint.py` imports matplotlib/numpy lazily
(inside `generate_heatmap`) so the JSON path needs neither.
