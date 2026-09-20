# AR-02B strict-Clippy receipt

Recorded with Rust/Clippy 1.96.0. The diagnostic command
`cargo clippy --release --all-targets -- -D warnings` exits nonzero on these
nine style lints. No lint suppression was added, and the experiment's selected
actions or generated result artifacts were not changed to address them.

| Location | Lint | Note |
|---|---|---|
| `src/ar02ar1.rs:518` | `too_many_arguments` | `make_verifier` has 8 arguments. |
| `src/ar02ar1.rs:579` | `needless_range_loop` | Group quota traversal indexes the quota array. |
| `src/ar02ar1.rs:611` | `needless_range_loop` | Class traversal indexes `by_class`. |
| `src/ar02ar1.rs:634` | `needless_range_loop` | Class traversal indexes likelihood storage. |
| `src/ar02ar1/output.rs:100` | `needless_range_loop` | Training samples are traversed by index. |
| `src/ar02ar1/r2.rs:21` | `enum_variant_names` | `PanelKind` variants share the `Replacement` suffix. |
| `src/ar02ar1/r2.rs:301` | `too_many_arguments` | `append_candidate` has 8 arguments. |
| `src/ar02ar1/r2.rs:417` | `too_many_arguments` | `audit_panel` has 9 arguments. |
| `src/ar02ar1/ar02b.rs:684` | `too_many_arguments` | `write_path_rows` has 9 arguments. |

The first eight sites are in copied AR-02A/R1/R2 support code; the last is in
the AR-02B output path. This receipt accepts the current lint debt for this
frozen diagnostic. It is not a claim that Clippy passes. Future code should
avoid adding to this list, and cleanup should be behavior-preserving with the
saved artifact checks rerun.
