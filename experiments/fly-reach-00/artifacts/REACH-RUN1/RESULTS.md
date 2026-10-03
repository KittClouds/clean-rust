# FLY-REACH-00

Disposition: **PARTIAL_DIRECTION_SUPPORT_SHORTFALL_WITH_EVALUATOR_FLOOR**

Native updates have near-zero alignment with the reference direction; reference directions improve the endpoint and full support improves further, but the stochastic evaluator prevents the frozen per-cell support rule from closing.

Final checkpoint means / support rates:

| arm | substrate | loss | support | large-bank loss |
|---|---|---:|---:|---:|
| native | fly | 0.304 | 17% | 0.301 |
| native | g001 | 0.296 | 29% | 0.295 |
| native | g002 | 0.297 | 21% | 0.295 |
| native | g003 | 0.311 | 17% | 0.309 |
| native | g004 | 0.311 | 12% | 0.310 |
| native | g005 | 0.290 | 25% | 0.289 |
| native | g006 | 0.295 | 21% | 0.293 |
| native | g007 | 0.279 | 29% | 0.276 |
| native | g008 | 0.298 | 25% | 0.297 |
| native_direction_reference_magnitude | fly | 0.280 | 25% | 0.274 |
| native_direction_reference_magnitude | g001 | 0.309 | 0% | 0.308 |
| native_direction_reference_magnitude | g002 | 0.306 | 12% | 0.304 |
| native_direction_reference_magnitude | g003 | 0.310 | 4% | 0.304 |
| native_direction_reference_magnitude | g004 | 0.305 | 8% | 0.304 |
| native_direction_reference_magnitude | g005 | 0.301 | 4% | 0.296 |
| native_direction_reference_magnitude | g006 | 0.308 | 17% | 0.303 |
| native_direction_reference_magnitude | g007 | 0.299 | 12% | 0.300 |
| native_direction_reference_magnitude | g008 | 0.308 | 8% | 0.307 |
| reference_direction_native_support | fly | 0.245 | 62% | 0.242 |
| reference_direction_native_support | g001 | 0.251 | 50% | 0.250 |
| reference_direction_native_support | g002 | 0.255 | 38% | 0.250 |
| reference_direction_native_support | g003 | 0.255 | 33% | 0.249 |
| reference_direction_native_support | g004 | 0.250 | 67% | 0.250 |
| reference_direction_native_support | g005 | 0.253 | 54% | 0.249 |
| reference_direction_native_support | g006 | 0.252 | 42% | 0.250 |
| reference_direction_native_support | g007 | 0.253 | 38% | 0.250 |
| reference_direction_native_support | g008 | 0.254 | 46% | 0.250 |
| reference_direction_full_support | fly | 0.240 | 71% | 0.237 |
| reference_direction_full_support | g001 | 0.246 | 67% | 0.244 |
| reference_direction_full_support | g002 | 0.249 | 58% | 0.244 |
| reference_direction_full_support | g003 | 0.250 | 58% | 0.244 |
| reference_direction_full_support | g004 | 0.246 | 67% | 0.245 |
| reference_direction_full_support | g005 | 0.248 | 58% | 0.244 |
| reference_direction_full_support | g006 | 0.249 | 67% | 0.245 |
| reference_direction_full_support | g007 | 0.246 | 58% | 0.245 |
| reference_direction_full_support | g008 | 0.249 | 58% | 0.244 |
| weight_oracle | fly | 0.236 | 62% | 0.231 |
| weight_oracle | g001 | 0.234 | 79% | 0.232 |
| weight_oracle | g002 | 0.236 | 71% | 0.231 |
| weight_oracle | g003 | 0.239 | 54% | 0.233 |
| weight_oracle | g004 | 0.238 | 67% | 0.232 |
| weight_oracle | g005 | 0.234 | 67% | 0.230 |
| weight_oracle | g006 | 0.243 | 58% | 0.239 |
| weight_oracle | g007 | 0.241 | 58% | 0.239 |
| weight_oracle | g008 | 0.229 | 79% | 0.224 |

Update diagnostics are retained separately. This is engineering qualification only; no biological mechanism or PHENO recovery claim is made.
