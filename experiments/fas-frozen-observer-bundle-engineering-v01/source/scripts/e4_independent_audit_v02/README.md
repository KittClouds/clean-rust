# E4-0 Independent Auditor v01

This package audits the frozen E4-0 contract/source map, population custody and freshness, parity and feature seals, and the terminal fresh-qualification result. It is an independent verification path; it does not import `e4_fresh_scorer_v01` or reuse its decision helpers.

The `contract`, `population`, `parity`, `features`, and `score` CLI modes each verify their required stage authorization before accessing the stage artifacts. Population auditing defers both terminal-label members in the population seal. Score replay reads the sealed scored-primary rows, predictions, metrics, bootstrap arrays, feature cache, row manifest, and verified E3 head tensors; it never reads either original population label file or held-out/joint escrow.

Run the synthetic suite from the experiment root:

```powershell
python -m unittest discover -s source\scripts\e4_independent_audit_v02\tests -v
python -m compileall -q source\scripts\e4_independent_audit_v02
$taskPythonPath = Join-Path (Get-Location) 'source\scripts'
$env:PYTHONPATH = $taskPythonPath
python -m e4_independent_audit_v02 --help
Remove-Item Env:\PYTHONPATH
```

The synthetic suite creates only temporary fixtures. Importing the package does not load a model, tokenizer, E4 row/cache artifact, or initialize CUDA.
