# Contextual institutional memory v1

Memory has a separate journal and memory.lbdb projection. Shared CAS is byte storage,
not an authority promotion. Memory writes never mutate the custody journal.

Kinds: OBSERVED, DERIVED, INTERPRETIVE, HYPOTHESIS, PREFERENCE, PROCEDURE,
DECISION, FAILURE_MODE, RESULT_SUMMARY. Observed/derived records require existing
custody references. A cited interpretation remains an interpretation.

Records bind scope, author, time, text, confidence, tags, custody references and exact
embedding bytes/model identity. Supersession adds events/edges; prior records remain queryable.
Search defaults to current memories. Filters can exclude hypotheses or require cited evidence.
Evidence-cited does not mean the memory's prose is independently proven true.

FTS, HNSW vector search and graph neighbors feed reciprocal-rank fusion. FTS refreshes
after writes before querying. Vector bytes are preserved for exact reconstruction;
query embeddings run CPU-only from local pinned model assets, without network download.
Search responses include trust class, grounding, references, supersession and retrieval surfaces.
Request retries return the previously committed search response, not a new ranking.
## Incremental lexical visibility

Native FTS indexes a frozen portion of the memory table. A Unicode word postings
overlay exposes recent committed records immediately. Full FTS reconstruction
occurs at doubling boundaries; vector-only queries do not rebuild FTS. Native
scores are BM25 and overlay scores are term overlap; they are retrieval ranks,
not correctness estimates. Projections and overlays rebuild from exact journals.
