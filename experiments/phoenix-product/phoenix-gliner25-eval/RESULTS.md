# GLiNER2.5 Base shadow evaluation — 2026-08-25

## Outcome

The exact `fastino/gliner2.5-base-v1` revision was exported and loaded by the
isolated Rust adapter. The native Rust decoder now implements all five feature
families, passes exact-structure Python parity, and completes measured probes on
all four Phoenix novels. The work remains candidate-only: nothing was published
to Phoenix graph or scene authority.

## Frozen lineage

| Input | Revision / digest |
| --- | --- |
| Phoenix source | `cbf349be8ee0dd878549242966d61b75fefe853f` |
| GLiNER2 Python | `3c913c7369301133d3b7699252074c4303ada50e` |
| gliner25-rs | `a639bad1ee744a7884deea2bd01512fddd886b8d` |
| Base model | `72ac19b486cd4557424c8d61114e7530c243e9b0` |
| Base config SHA-256 | `0eb92d00584d613aab32b2178f84a85176b62c87ae3689ce9084e83f6eba64d1` |
| ONNX manifest SHA-256 | `1cfea3cc7bcef60f0ecdde1590828a21a8d831401cb5766920227dbbf82ce550` |
| Evaluator Cargo.lock SHA-256 | `05577ec701d0b3f634c1859fcf12857c38488c91b43f911effc6de9eb02a9280` |

The exported manifest records boundary architecture v1, feature-head contract
v2, hidden size 768, a shared pool of 192 candidates,
64/128/256/320/384/448/512 word buckets, abstention and count heads, relations
enabled, records enabled, and flat overlap policy. The explicit-span head has
8x32 and 16x64 exact tiers plus the canonical cap of 64 queries and 128 spans
per call; the sparse relation scorer is capped at 32 relation types and 64
endpoint pairs per call.

## Parity

The frozen 12-case suite yielded 43 Python spans and 43 Rust spans.

- Identical text, label, and half-open byte range: `43/43` (`100%`)
- Maximum recorded FP32 score delta: `0.0000`
- Invalid source ranges: `0`

This covers prompt construction, marker routing, candidate decoding,
abstention, and overlap resolution in addition to the ONNX fragments.

### Five-feature decoder parity

The feature-head v2 suite compares the Python reference and Rust decoder after
both consume the same frozen ONNX artifacts.

| Feature | Structure | Maximum probability delta |
| --- | --- | ---: |
| Long context | exact | `1.3709068e-6` |
| Unlimited explicit spans | exact | `2.6226044e-6` |
| Span attributes | exact | `6.2584877e-7` |
| Constrained classification | exact | `5.9132373e-8` |
| Joint entity-relation IE | exact | `3.4882139e-7` |

Overall maximum probability delta was `2.6226044e-6`; the constrained
classification objective delta was `5.2452087e-6`. Both are below the frozen
`1e-5` and `1e-4` gates. A repeated Rust run was value-identical, all expected
statuses were observed, and graph publications remained zero.

## Five decoded feature probes

| Feature | Observed evidence |
| --- | --- |
| Long context | Four entities recovered near byte 8,900 of a 900-word synthetic document; 4/4 spans valid |
| Unlimited span candidate | 18-word, 113-byte treaty title extracted; three attempted spans valid |
| Joint entity + relation IE | Five typed entities and two `works_for` edges under typed endpoints |
| Constrained classification | Exact decoder returned feasible `intent=delete`, `effects=[delete]`, zero violations |
| Span attributes | `iPhone camera` received a span-conditioned positive sentiment attribute |

These observations are emitted by both the Python reference and Rust decoder
with exact structure. The Rust implementation includes exact model-word chapter
windows with byte-offset restoration, described explicit-span queries,
span-conditioned attributes, an exact constrained combinatorial solver, and a
sparse typed-endpoint relation decoder with overlap, self-edge, beam, and cap
policies. Record decoding is a separate surface and is not claimed here.

## Four-novel census

Inputs: `shortrun.md`, `midrun.md`, `laterun.md`, and `endrun.md`. The raw run
keeps all four for performance coverage. Interpretation excludes `shortrun`
because its chapters are duplicated inside `midrun`.

| Metric | Result |
| --- | ---: |
| Input bytes | 1,952,025 |
| Whitespace words | 317,386 |
| Chapter-bounded windows | 1,323 |
| Model words processed (overlap included) | 491,613 |
| Retained candidates | 29,159 |
| Overlap duplicates removed | 3,523 |
| Invalid source ranges | 0 |
| Elapsed | 797.403 s |
| Throughput | 616.52 model words/s |
| Peak working set | 1,207,242,752 bytes |
| JSONL BLAKE3 | `54b527a8b2e969df5a3f0ddc3cd5aa1347553d508b821e9ecc823de94dfe344b` |
| Graph publications | 0 |

Label counts after excluding the duplicated `shortrun` file:

| Label | Candidates |
| --- | ---: |
| person | 12,273 |
| item | 3,809 |
| location | 3,181 |
| concept | 2,648 |
| organization | 1,336 |
| event | 1,116 |
| group | 946 |
| creature | 768 |
| temporal expression | 556 |
| memory | 72 |
| causal trigger | 16 |

These are model candidate counts, not accepted Phoenix facts and not gold-set
precision or recall.

## Performance

### Native decoder optimization pass — 2026-08-26

The accepted implementation removes Rust-to-ORT input tensor copies, retains
the already-constructed padded word mask in each trace, lazily loads scorer
sessions, selects the smallest fitting explicit-span tier, and selects the
smallest fitting boundary bucket. The dense-bucket Python/Rust parity gate is
exact for all five structures; maximum probability delta remains
`2.6226044e-6`, classification-objective delta remains `5.2452087e-6`, and
graph publications remain zero.

Against the original four-novel benchmark, all measured repetitions retained
identical output counts and maximum peak working set fell from 1,291,980,800 to
1,222,438,912 bytes (`-5.38%`). The final rebuilt 7-run shortrun probe measured
p50 reductions of `2.61%` to `11.09%` across the five surfaces, but the separately launched
four-novel aggregate did not reproduce a throughput win: its matched p50
geometric mean was `3.44%` slower and varied in both directions by document and
feature. Therefore the accepted claim is lower memory and exact behavior, not a
universal latency improvement. The encoder remains the dominant hot path.

Two experiments were rejected. A 511-word caller window changed stable output
counts (`80` to `51`) and cannot be adopted without a human gold set. Dynamic
INT8 reduced the encoder file size but failed structural parity on every feature
and moved the classification objective by `17.1548`; the quantized artifact and
runtime fallback were removed. Full receipts and commands are indexed in
`OPTIMIZATION.md`.

### Native five-feature novel probes

Release build, eight ORT intra-op threads, one warmup and three measured runs
per feature. Full windows use 270 model words for the four short-context
features and 900 model words for long-context orchestration. `midrun` reaches a
chapter boundary at 141 model words, so its latency is not directly comparable
to the three full windows.

| Novel | Engine load | Model words short/long | Long p50 | Wide p50 | Attributes p50 | Classification p50 | Joint p50 | Peak working set |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `shortrun.md` | 13.80 s | 270 / 900 | 1430.24 ms | 381.63 ms | 434.77 ms | 327.47 ms | 500.09 ms | 1227.91 MiB |
| `midrun.md` | 12.85 s | 141 / 141 | 214.26 ms | 226.11 ms | 279.17 ms | 215.83 ms | 291.25 ms | 1086.08 MiB |
| `laterun.md` | 12.19 s | 270 / 900 | 1397.85 ms | 360.50 ms | 428.52 ms | 318.51 ms | 358.02 ms | 1190.71 MiB |
| `endrun.md` | 12.21 s | 270 / 900 | 1419.00 ms | 389.87 ms | 447.28 ms | 353.38 ms | 514.29 ms | 1232.13 MiB |

Every measured repetition returned the same output count for its document and
feature. Across the four documents, median document p50 was 1408.43 ms for long
context, 371.07 ms for wide spans, 431.64 ms for attributes, 322.99 ms for
classification, and 429.06 ms for joint IE. These are performance and
determinism measurements, not accuracy measurements.

FP32, 11-label story schema:

| Workload | Device intent | Runs | p50 | p95 | p99 | Working-set drift |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 8 whitespace words | CUDA | 100 | 57.10 ms | 68.54 ms | 82.52 ms | +122,880 B |
| 8 whitespace words | CPU | 100 | 121.61 ms | 161.37 ms | 174.49 ms | +69,632 B |
| 313 model words | CUDA | 30 | 486.76 ms | 510.45 ms | 520.92 ms | +405,504 B |
| 313 model words | CPU | 30 | 420.51 ms | 474.49 ms | 511.27 ms | +364,544 B |

CUDA intent helps tiny requests but loses on the long window on this machine.
The crate registers an execution-provider request but cannot report which
provider served each fragment, and its exported FP16 I/O-binding layout is not
backed by actual ORT I/O binding. The measured FP16 long-window p50 was about
11 seconds and is rejected for this adapter.

### Active-head comparison

The fair comparison uses the exact label intersection supported by the active
GLiNER-BI vocabulary: `Person`, `Location`, `Organization`, `Creature`, `Item`,
`Concept`, and `Event`. Both heads received identical text. The active-head
figures are its prepared-label path; the boundary-head figures are FP32 CPU.

| Workload | Head | Runs | Load | Median / p50 | p95 |
| --- | --- | ---: | ---: | ---: | ---: |
| Short probe | Active GLiNER-BI | 100 | 1.374 s | 16.90 ms | 19.52 ms |
| Short probe | GLiNER2.5 Base boundary | 100 | 13.241 s | 125.82 ms | 146.75 ms |
| First 270 whitespace words of `shortrun.md` | Active GLiNER-BI | 30 | 1.123 s | 247.67 ms | 278.26 ms |
| Same 270-word text (313 model words) | GLiNER2.5 Base boundary | 30 | 12.865 s | 444.80 ms | 498.18 ms |

On these controlled CPU probes, the boundary head was 7.45x slower at the
short median and 1.80x slower on the novel-window median. The active model's
fixed label vocabulary cannot express `group`, `temporal expression`, `causal
trigger`, or `memory`; those are capability differences, not quality wins.
Without a human gold set, candidate counts and prediction counts cannot decide
which head is more accurate.

## Boundary discoveries

1. The upstream exporter fails on a default Windows CP-1252 console when Torch
   prints a Unicode success glyph. Forcing `PYTHONUTF8=1` resolves the tooling
   failure without modifying model code.
2. A 384-whitespace-word novel chunk became 547 runtime model words. The
   evaluator now uses the exact Rust model-word regex, which prevents windows
   from exceeding the 512-word head.
3. The active Phoenix process remains on its qualified GLiNER-BI and ModernBERT
   pipeline. This workspace is process- and ABI-isolated because Phoenix uses
   ORT rc.9 while the new crate requires rc.13 or newer.
4. `ORT_DYLIB_PATH` is part of the executable boundary. Omitting it allowed the
   evaluator to inherit an older machine-wide ONNX Runtime and fail on an IR 10
   fragment (`max supported IR version: 9`). Pinning the isolated rc.13 DLL
   made the same artifact load and run successfully.
5. The Python processor appends terminal punctuation when source text lacks
   `.`, `?`, or `!`. Rust now mirrors that model-facing behavior while retaining
   caller byte coordinates and records caller-word versus model-word counts.
6. The first joint decoder let a weaker rescued endpoint overwrite a stronger
   ordinary entity candidate. The merge now retains the maximum logit; rescue
   only restores a missing endpoint.
7. The relation exporter normalized distance using the padded bucket length,
   not the true document word length. Feature-head contract v2 adds an explicit
   `text_length` input, and Rust passes the trace's model-word count.

## Open gates before integration

- Freeze a human-judged novel gold set before reporting precision, recall, F1,
  relation F1, attribute accuracy, or promotion readiness.
- Build a human-judged, same-schema comparison set; the controlled latency
  comparison against active GLiNER-BI is complete.
- Decide whether and how the candidate-only Rust five-feature surface should
  enter Phoenix's evidence-bound extraction authority. This experiment does not
  make that promotion decision.
- Qualify record decoding separately; it is not part of the five-feature cut.
- Add an explicit served-provider receipt or I/O-binding implementation before
  treating CUDA/FP16 as a production performance path.
- Keep candidate outputs behind evidence-bound decision receipts; do not let a
  model output become topology merely because it is visible.
