# Q10-RC result

Status: `Q10_RC_INVALID`

Stage A opened engineering seed `9601` and failed closed before producing a valid event bundle. The retained-subspace pseudoinverse reconstruction error was `4.1484338125790275e-7`, exceeding the frozen `2e-10` integrity limit. No scientific seed, behavioral observable, repair, or multi-move evaluation was used.

The failure is consistent with the rank-deficient SVD-left-vector instability previously identified in Q09. A QR reconstruction through the frozen retained right subspace is an engineering correction, but it changes the implementation after Stage A began. Therefore Q10-RC cannot resume under this identity. Any corrected qualification requires a new protocol identity and fresh engineering seeds.
