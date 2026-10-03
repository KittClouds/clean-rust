# DH-05 measured results

**TRAJECTORY_ASSAY_COMPLETE**

DH-05 measured the DH-04 causal cells at declared reversal checkpoints.

Final old-map probe, retained minus suppressed: **-7.837 pp**; 95% [-8.683, -6.999].

Final acquisition-axis projection, retained minus suppressed: **-3.180462**; 95% [-3.556672, -2.799910].

768 arm runs; 393,216 computed training trials; 24 fresh seed bundles; two taus; one specimen.

## Right-slice E trajectory means

| Field | Condition | t=0 | t=16 | t=32 | t=64 | t=128 | t=256 |
|---|---|---:|---:|---:|---:|---:|---:|
| old_map_margin | immediate | +0.051093 | +0.046057 | +0.041144 | +0.033306 | +0.016931 | -0.008443 |
| old_map_margin | quiet | +0.051093 | +0.050332 | +0.049686 | +0.048371 | +0.044404 | +0.034457 |
| old_map_margin | eligibility_retained | +0.051093 | +0.047057 | +0.043848 | +0.038527 | +0.031004 | +0.020299 |
| old_map_margin | eligibility_suppressed | +0.051093 | +0.049886 | +0.048649 | +0.046489 | +0.041996 | +0.033417 |
| reversed_map_margin | immediate | -0.051093 | -0.046057 | -0.041144 | -0.033306 | -0.016931 | +0.008443 |
| reversed_map_margin | quiet | -0.051093 | -0.050332 | -0.049686 | -0.048371 | -0.044404 | -0.034457 |
| reversed_map_margin | eligibility_retained | -0.051093 | -0.047057 | -0.043848 | -0.038527 | -0.031004 | -0.020299 |
| reversed_map_margin | eligibility_suppressed | -0.051093 | -0.049886 | -0.048649 | -0.046489 | -0.041996 | -0.033417 |
| acquisition_axis_coordinate | immediate | +1.000000 | +0.939633 | +0.887308 | +0.797843 | +0.669722 | +0.568943 |
| acquisition_axis_coordinate | quiet | +1.000000 | +0.975544 | +0.945822 | +0.887873 | +0.781511 | +0.648307 |
| acquisition_axis_coordinate | eligibility_retained | +1.000000 | +0.924063 | +0.866800 | +0.800607 | +0.721322 | +0.659964 |
| acquisition_axis_coordinate | eligibility_suppressed | +1.000000 | +0.984287 | +0.970159 | +0.944282 | +0.896412 | +0.827932 |
| acquisition_axis_projection | immediate | +18.735814 | +17.604194 | +16.629760 | +14.955714 | +12.552804 | +10.635363 |
| acquisition_axis_projection | quiet | +18.735814 | +18.275151 | +17.719870 | +16.629386 | +14.614804 | +12.086451 |
| acquisition_axis_projection | eligibility_retained | +18.735814 | +17.316005 | +16.251476 | +15.001097 | +13.506082 | +12.331510 |
| acquisition_axis_projection | eligibility_suppressed | +18.735814 | +18.441681 | +18.179553 | +17.695841 | +16.800538 | +15.511972 |
| reversal_parallel_projection | immediate | +0.000000 | -1.131621 | -2.106054 | -3.780100 | -6.183010 | -8.100451 |
| reversal_parallel_projection | quiet | +0.000000 | -0.460663 | -1.015944 | -2.106428 | -4.121010 | -6.649363 |
| reversal_parallel_projection | eligibility_retained | +0.000000 | -1.419809 | -2.484338 | -3.734717 | -5.229732 | -6.404304 |
| reversal_parallel_projection | eligibility_suppressed | +0.000000 | -0.294134 | -0.556261 | -1.039973 | -1.935276 | -3.223842 |
| reversal_perpendicular_norm | immediate | +0.000000 | +0.166455 | +0.234048 | +0.326253 | +0.456782 | +0.692846 |
| reversal_perpendicular_norm | quiet | +0.000000 | +0.054050 | +0.085927 | +0.138868 | +0.214637 | +0.311225 |
| reversal_perpendicular_norm | eligibility_retained | +0.000000 | +0.337854 | +0.446602 | +0.584694 | +0.735934 | +0.957579 |
| reversal_perpendicular_norm | eligibility_suppressed | +0.000000 | +0.044658 | +0.063443 | +0.091446 | +0.133244 | +0.202293 |

## Integrity and limits

- Acquisition hashes, checkpoint vectors, DH-04 causal compatibility, same-RNG probe complements, event counts, and zero online allocations passed.
- Simulator execution including setup and diagnostics: 12.952 seconds on 4 workers.
- Margins and weight projections are model diagnostics. The trajectory does not establish a biological mechanism.
- No new intervention, rule search, extra seed, or post-outcome tuning.

Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. https://male-cns.janelia.org/download/
