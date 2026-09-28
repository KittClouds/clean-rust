# Runtime provenance and licenses v1

runtime/ASSET-MANIFEST-v1.json hashes the captured runtime files. requirements-lock-v1.txt
pins Python distributions; wheel archives retain their metadata/licenses. Native Ladybug
comes from the official v0.20.2 Windows release; FTS/vector extensions were captured from
the official extension installer. The extension ABI directory is 0.20.0, as reported by
the installed native runtime; it is not inferred to be package version 0.20.2.

OpenSSL DLLs were captured from the installed Git for Windows distribution. Their hashes
are qualified alongside Ladybug. These are local runtime assets, not an assertion of
relicensed redistribution. Retain upstream licenses when packaging outside this host.

FastEmbed BAAI/bge-small-en-v1.5 CPU ONNX assets and tokenizer bytes were captured from
the downloaded model snapshot. Embedding.manifest binds actual files/dimensions; no
automatic runtime network update is permitted. This model is infrastructure retrieval,
not an E013/JEV/Fabrique frozen scientific observer.
