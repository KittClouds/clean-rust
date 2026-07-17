# Phoenix Obscura worker

This standalone Rust workspace isolates untrusted page JavaScript and V8 from
the Phoenix desktop process. It accepts one bounded JSON request on stdin,
returns one JSON response on stdout, and exits. Phoenix never exposes Obscura's
CDP or MCP network servers.

The Obscura dependencies are pinned to audited revision
`b2e4bb49a7723619527fd0cbb9f2c2acbc58f851`. The separate workspace is
intentional: Phoenix releases use `panic=abort`, while Obscura requires
`panic=unwind` around V8 operations.

## Windows build

Keep both Cargo's registry and target on `D:` so `rusty_v8` does not require a
privileged cross-volume directory symlink:

```powershell
$env:CARGO_HOME = 'D:\phoenix-cargo-home'
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-obscura\renderer'
cargo build --release --manifest-path rust\phoenix\sidecars\phoenix-obscura-worker\Cargo.toml
$env:PHOENIX_OBSCURA_WORKER_PATH = 'D:\phoenix-target-obscura\renderer\release\phoenix-obscura-worker.exe'
```

The parent applies a process deadline and a Windows Job Object with kill-on-
close and a 512 MiB process-memory limit. Override the latter only with
`PHOENIX_OBSCURA_MAX_RSS_BYTES`; values are clamped to 64 MiB through 2 GiB.

## Default security posture

- HTTP and HTTPS only; embedded credentials are rejected.
- Private-network access, inherited proxy settings, and stealth are removed.
- No persistent profile, file access, listening socket, or arbitrary script API.
- Rendered output, stderr, request size, wall time, and extracted source bytes
  are independently bounded.

Obscura is Apache-2.0 licensed. Any binary distribution must ship the upstream
license from <https://github.com/h4ckf0r0day/obscura/blob/main/LICENSE>.
