# NewPhoenix

Native-first Phoenix workspace for the Angular frontend, Tauri desktop shell, native Rust Phoenix crates, local model assets, and `docs/` corpus/docs.

The active branch is intentionally slimmed down to avoid accidentally compiling legacy GoKitt/WASM/reference targets.

## Start The Frontend

```powershell
npm install
npm start
```

Open `http://localhost:4200` for browser development.

## Start The Tauri Native Shell

Run this in another terminal while `npm start` is running:

```powershell
npm run desktop:dev
```

The desktop scripts pin Cargo outputs to `D:\cargo-targets\Angular-build\tauri-dev` so every developer command launches the same binary family. Use `npm run desktop:contract` before committing native RPC changes.

## Native Rust Work

Use `rust-native/phoenix` for current native Phoenix work:

```powershell
$env:CARGO_TARGET_DIR='D:\cargo-targets\Angular-build\tauri-dev'
cargo check --manifest-path "rust-native\phoenix\Cargo.toml" -p phoenix-dynamic-ner -p phoenix-embed
```

The `rust/phoenix` tree remains only as the current Tauri compatibility shim for `src-tauri`; do not add new feature work there.

## More Notes

See `docs/newphoenix-startup.md` for model paths, Dynamic NER benchmark commands, Semantic Atlas probe commands, and branch rules.
