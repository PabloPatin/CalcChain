# CalcChain Two Local Sources Import Example

This example demonstrates a complete local CalcChain flow:

- load code from `sources/code`;
- load input files from two separate local folders, `sources/measurements` and `sources/calibration`;
- run a Python calculation in the CalcChain work directory;
- publish/import calculated files into another local folder, `imported_results`.

Run it from the repository root:

```powershell
python examples/two_local_sources_import/run_demo.py
```

The calculation folder is created at:

```text
examples/two_local_sources_import/job/work
```

CalcChain service metadata for the job is created at:

```text
examples/two_local_sources_import/job/.calcchain
```

The imported calculation outputs are created at:

```text
examples/two_local_sources_import/imported_results
```

`run_demo.py` recreates `job`, `service_publish`, and `imported_results` on each run. The static source folders under `sources` are left unchanged.
