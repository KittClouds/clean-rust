# E4-0 engineering readiness review packet

**Prepared:** 2026-09-28  
**Purpose:** Independent review of the already-bound E4-0 scoring handoff, so the next action can be a single scoped scoring decision and E4-01 can proceed as soon as its existing entry gate permits.  
**Status:** Engineering preparation complete for review. E4-0 scoring is not authorized or run. E4-01 remains closed.

## Decision requested from the reviewer

Please review the frozen E4-0 contract binding, the final Fabrique v02 scoring adapter, and Chief’s Ledger preparation receipt. Return one of:

- **READY FOR SCOPED E4-0 SCORING AUTHORIZATION**, or
- **BLOCKED**, with the exact artifact, field, or protocol mismatch.

Please limit requested changes to a demonstrated mismatch, custody leak, or execution defect. The task is a readiness review, not a new protocol design exercise. A positive review is a recommendation; it does not itself issue a scoring grant or open the panel.

This is a pre-execution engineering review. The E4-0 scoring outputs do not exist yet, so this packet makes no scientific claim. Once scoring is complete, the raw result still goes through the program’s raw-result-first scientific review before any synthesis becomes direction for Fabrique.

## What is complete

### 1. Shared Library acceptance and E4 history

Kammi Ledger’s acceptance suite passed **28 gates and 47 tests**. The accepted service uses CAS plus the journal as authority and Ladybug as its rebuildable projection. The live service currently reports the journal and projection at the same head, zero panel exposures, and no active leases.

- Acceptance identity: sha256:2578de42c94f7f8cbed72521cb582a47bea465039f7a485ecce30ec1fcd7a898
- Source root: sha256:8019d2281747a5b9d4572e58770fa7ec671c744d9274be43dea3a17ac001a10c
- Acceptance terminal: [TERMINAL.json](<C:/code land/clean-rust/program-infrastructure/kammi-ledger/acceptance/endstate/qualified-20260928T013045943444Z/TERMINAL.json>)
- Current journal/projection head: sha256:1daa57189e0b9f886ffeb2444629ca3cb40f01cc40bcd6b97de8ca5f022d5a1a

The Library acceptance demonstrates the custody and execution service boundary. It does not authorize E4 science by itself.

### 2. E4-0 frozen work already completed

The governing E4-0 contract is sealed:

- Contract: [e4-0-contract-v16-v09-final.json](<C:/Users/shuga/.codex/worktrees/e4-0-contract-work/clean-rust/experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v09-final.json>)
- Contract SHA-256: 21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f
- Seal: [e4-0-contract-v16-v09-seal.json](<C:/Users/shuga/.codex/worktrees/e4-0-contract-work/clean-rust/experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v16-v09-seal.json>)
- Seal SHA-256: 0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c

Supervised parity and feature extraction stages have completed. Chief’s custody audits report the expected worker/output custody and released fences. Their scope is custody and output identity; they do not claim an independent scientific recomputation of parity. The extraction audit records that no protected primary labels were opened.

- [Parity custody audit](<C:/code land/clean-rust/program-infrastructure/governance/inbox/20260927/E4-0-PARITY-CUSTODY-AUDIT-v1.json>)
- [Feature extraction custody audit](<C:/code land/clean-rust/program-infrastructure/governance/inbox/20260927/E4-0-EXTRACT-CUSTODY-AUDIT-v1.json>)
- Extracted cache: 1,223,360,512 bytes; SHA-256 49236412bf7409bd5f8d2c15f43436afa17940d51cc4bfdcdaf9d773029deac4
- Custody lineage for scoring binds to the extracted-stage seal sha256:cd0116883e679a83707c472f8edef0e08333773d971b1f3fc33ad22a22a1396e

### 3. Fabrique scoring implementation, candidate v02

Fabrique produced a runnable local scoring adapter and native execution packet. Its synthetic-only qualification passed **11/11 tests**. The identity audit passed. Qualification read no E4 label bytes, feature-cache bytes, or E3 head payloads and made no tokenizer, model, CUDA, or Ledger contact.

- [Fabrique execution-spec candidate v02](<C:/Users/shuga/.codex/worktrees/e4-0-contract-work/clean-rust/experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-scoring-stage-candidate-v02/e4-0-scoring-execution-spec-candidate-v02.json>) — SHA-256 80e24afa298c8db0c8300e83715155d10e131762bbef0cf9ac51049e13c1acfa
- [Native local execution spec candidate v02](<C:/Users/shuga/.codex/worktrees/e4-0-contract-work/clean-rust/experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-scoring-stage-candidate-v02/kammi-local-execution-v1-candidate-v02.json>) — SHA-256 d3c38aabd7da770bc3d417d48e4aa03c8d784954cd7713725842cba40c7d2e1f
- [Fabrique candidate receipt v02](<C:/Users/shuga/.codex/worktrees/e4-0-contract-work/clean-rust/experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-scoring-stage-candidate-v02/e4-0-scoring-candidate-receipt-v02.json>) — SHA-256 1673b234263217bca517eb114728181e7227937f9e2ffdef024254e9cac2cfe8
- [Fabrique packet identity audit v02](<C:/Users/shuga/.codex/worktrees/e4-0-contract-work/clean-rust/experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-scoring-stage-candidate-v02/e4-0-scoring-candidate-audit-v02.json>) — SHA-256 dba837f7a928eb4ea7c8b6734dd1f95e4baeee8ce0afcdb503baed3694c0faeb

The candidate binds the frozen E4/E3/scorer inputs, all 20 E3 head/scaler identities, feature-cache and row-manifest metadata, and a 35-source worker manifest. It declares seven expected outputs: predictions, scored rows, metrics, bootstrap output, label-open receipt, terminal receipt, and stage seal.

### 4. Chief’s Ledger binding and preparation

Chief bound the exact candidate execution spec to the existing E4-0 scoring stage and run. It is covered by a verified spec seal and a successor preparation seal:

- Stage: E4_0_FRESH_QUALIFICATION_SCORING_V1
- Run: frozen-fabrique.e4-0.supervised.v1
- Actor: fabrique-e4-supervisor-v1
- Bound spec seal: sha256:b78318974edf607d22136279f35164c6505c8bcf9e7ba4a160f5269083f28c18
- Prepared artifact: sha256:d807cbdc2cc53fcb83804690cfb281f4ae4b67c37f07b6e3a48e4c7ff58ef851
- Prepared successor seal: sha256:251a3e980c1923664b2b6b2aa7fefd9976ba5c64a67d8ba7910ba055537e23a9
- [Chief preparation receipt](<C:/code land/clean-rust/program-infrastructure/governance/inbox/20260928/E4-0-SCORING-PREPARED-LEDGER-RECEIPT-v1.json>)

The receipt explicitly records: scoring_authorized=false, panel_exposures=0, e4_01_entry_open=false. The stage-preparation receipt records that the scoring grant, panel-open grant, execution lease, and stage authorization have not been issued.

## Remaining gate and bounded next steps

There is one substantive E4-0 action left: conduct the separately authorized primary scoring stage, then independently replay/audit the outputs and write the E4-0 terminal disposition. The reserved panel is e4-0-primary-terminal-v01. Its expected bytes are 39,363,264 with SHA-256 225787239ffb3d3920e2c299f0f05cdb59df88a89ddc11ed22edde9ac312a365. It has not been registered or opened.

If the reviewer returns READY and the required scoring authority is issued, the bounded execution sequence is:

1. Issue the one stage-scoped authorization and execution lease through Kammi Ledger.
2. Open the reserved primary panel once for terminal scoring; stage and hash-verify it before worker launch.
3. Run the already-bound scorer and produce only the seven declared outputs.
4. Independently replay and audit them; record the E4-0 terminal disposition and reconcile custody.

The held-out-template and joint-template truth remain escrowed for their separate contract. This scoring action does not open them.

E4-01 remains closed until E4-0 has a viable terminal disposition and its custody is reconciled. Once that gate is satisfied, the recommendation is to proceed directly to the existing E4-01 entry review, without reopening completed parity/extraction work or redesigning the shared Library. No new protocol or scientific claim is proposed in this packet.

## Reviewer response

Please return:

- Decision: READY FOR SCOPED E4-0 SCORING AUTHORIZATION / BLOCKED
- Exact blockers, if any, with the artifact and field or check involved
- Confirmation that the review did not inspect protected primary, template, or joint label contents

A READY response allows Chief to route the already-prepared stage for the separate scoring authorization decision. It is not itself a grant, exposure, execution, or E4-01 authorization.
