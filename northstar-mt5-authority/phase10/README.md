# RG2 Phase 10

Phase 10 adds six frozen, semantically unchanged windows selected from the
Phase 9 coverage gaps. It then reruns Phase 9 and the lifecycle audit before
creating a deterministic corpus seal.

The target batch adds one window per instrument and balances missing common or
directional sampling strata. Outcome labels are never used to alter grammar or
to manufacture rare observations.

```powershell
$py = 'C:\Users\shuga\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py phase10\phase10.py plan
& .\Invoke-MasterStructureDataFurnace.ps1 -WindowId <six frozen IDs>
& $py phase9\run_phase9.py
& $py phase9\run_lifecycle_audit.py
& $py phase10\phase10.py seal
& $py phase10\phase10.py verify
```

The seal is contractual and content-addressed. Existing raw run directories are
never rewritten; semantic changes require a new research/corpus generation.
