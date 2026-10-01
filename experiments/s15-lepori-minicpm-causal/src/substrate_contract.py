"""Lepori causal lane -- frozen substrate contract.

Identity of the backbone this lane is built on, and the lessons inherited from the parked
encoder lineage. Nothing in this file trains anything; it is the thing a later agent must not
silently change.

WHY THIS SUBSTRATE
    MiniCPM5-1B-Base, a plain `LlamaForCausalLM` (`model_type: llama`). Chosen because it is
    the one previously-validated causal backbone in this repo that exposes a FULL internal
    hidden-state stack, which is exactly the property the graft program needs and exactly the
    property K2-Horizon lacks. K2's custom `K2HorizonModel.forward` absorbs
    `output_hidden_states` into `**kwargs`, never appends to `all_hidden_states`, and returns
    only `last_hidden_state` -- so it is final-layer-only and would have blocked internal
    surfaces. That is an integration risk, not an interesting scientific question, and it is why
    K2 is not the choice today.

QUALIFIED FACTS (see substrate-qualification.json)
    parameters              1,080,632,832 (1.0806B), bf16, frozen
    architecture            LlamaForCausalLM, no trust_remote_code needed
    hidden_size             1536
    layers                  24
    hidden_states tuple     length 25, fully populated  <-- the decisive property
    validated depths        25/50/75/100% -> layers 6 / 12 / 18 / 24
    weight identity         EXACT against on-disk safetensors, worst max-abs-diff 0.0
    padding correctness     cosine >= 0.99998 and relative RMS <= 0.006 at all four depths

    The weight-identity check exists because of the LFM2.5-Encoder-230M incident: loading a
    wrapper with bare `AutoModel` silently random-initialized every weight there. A load is not
    trusted here until it is compared against the checkpoint on disk.

HIDDEN SCALE VARIES SHARPLY WITH DEPTH -- this constrains the surface design
    std of hidden states:  layer 6 = 22.21   layer 12 = 22.91
                           layer 18 = 23.59  layer 24 = 3.73
    The final layer is ~6x smaller in scale than mid-depth. Consequences, recorded so they are
    not rediscovered by accident:
      * surfaces from different depths must not be summed or averaged without per-surface
        normalisation, or the shallow surfaces will simply dominate;
      * any variance floor or diversity diagnostic is only comparable WITHIN a surface, never
        across depths;
      * this is a substrate property, not a bug, and it is a real difference from the encoder
        lane (LFM2.5-230M, hidden 1024, 14 layers).

INHERITED FROM THE ENCODER LINEAGE (parked, not rescued)
    These are program-level lessons. They are inherited as constraints, not as an architecture.

    1. EXHAUSTIVE CANDIDATES. m_cap = 28, the measured canonical maximum over 140,000 BANK-v1
       worlds. Retain every canonical candidate. The encoder's m_cap = 24 silently DROPPED whole
       rows whose worlds had >24 actions: 21,016 worlds, 15.0% of the canonical universe, and
       567,254 candidates that were never reachable. Never let a cap be a typed constant
       without an audit against the measured maximum.
    2. NO RAW LATENT-MATCHING LOSS. `||s(x) - s(x-tilde)||^2` has its global minimum at constant
       s. On the encoder it drove D_s to 0.0007 while looking like successful optimisation.
       Renderer invariance is enforced on PREDICTIONS (Jensen-Shannon), never on latents.
    3. DIVERSITY IS NOT COMPETENCE. D_s > 0 does not imply semantic discrimination. The encoder
       reached D_s 1.84 (172x its floor) with every global target still at 0.500 balanced
       accuracy. Variance rules out collapse; it is not evidence of usefulness, and it is never
       reported as a success metric on its own.
    4. PAIRED CORRECTNESS, NOT NAKED RENDERER AGREEMENT. A constant predictor is perfectly
       renderer-stable for the wrong reason. Always report the 2x2 decomposition: both correct /
       first only / second only / both wrong, plus disagreement. The encoder produced three
       global heads with ZERO disagreement and majority-rate accuracy -- stability that meant
       nothing.
    5. NO DUPLICATE-SOURCE WEIGHTING. Weight over independent CANONICAL SOURCES, not ontology
       head count. On BANK-v1, 13 heads resolve to 6 independent sources:
       candidate_applicable == candidate_legal,
       candidate_has_unmet_requirements == 1 - candidate_legal,
       number_or_structure_of_missing_requirements[ch0] == missing_information_present.
       A source contributes one unit: L_g = (1/|H_g|) sum_h L_h.
    6. BALANCED OBJECTIVE AND CORRECT SELECTION. Class-imbalanced BCE is minimised by predicting
       the prior, and a prior-dominated selection rule prefers the most collapsed checkpoint.
       Use balanced BCE with TRAIN-only prevalence, and select on J_select over unique source
       groups. Encode the margin BEFORE looking: a target counts as risen only if balanced
       accuracy exceeds max(pi, 1-pi) by a pre-registered margin.
    7. NO GENERIC GLOBAL-TOKEN / CANDIDATE-TOKEN RECURRENT MIXER. Phase 4A's shared-weight
       block moved the state enormously (D_s 172x) while destroying candidate conditioning
       (6.53 -> 1.53) and collapsing renderer paired accuracy. Self-attention over one global
       token plus candidate tokens homogenises exactly the candidate differentiation this lane
       actually earns. Any future recurrent organ needs a different job, not more depth.
    8. PORT THE CONTRACT, NOT THE GRAFT. The bidirectional graft is not being ported. This lane
       builds a causal-appropriate interface on MiniCPM's validated surfaces. Candidate-local
       structure, the collapse/objective findings, and the mixer warning are inherited as
       constraints.

WHAT THIS LANE JOINS AT
    The current constructive frontier, not archaeological Layer 1. Lessons 1-7 are already
    banked; this lane does not replay them. Same System 1.5 destination, different substrate.
"""
from __future__ import annotations

import json
from pathlib import Path

CONTRACT = {
    "abi": "s15-lepori-minicpm/substrate-contract-v0.1",
    "lane": "Lepori",
    "fabric": "causal",
    "role": "second causal substrate, paired with Lexi (LFM2.5-230M causal)",
    "parked_lineage": {
        "name": "Encoder (LFM2.5-Encoder-230M bidirectional)",
        "status": "PARKED, preserved, not rescued",
        "final_verdict": "state motion without useful computation",
        "artifacts_preserved": [
            "D:/codex-runs/encoder-contrast-01/phase0", "D:/codex-runs/encoder-contrast-01/phase1",
            "D:/codex-runs/encoder-contrast-01/phase2", "D:/codex-runs/encoder-contrast-01/phase3",
            "D:/codex-runs/encoder-contrast-01/phase4a",
        ],
        "reopen_condition": "an encoder-specific program shaped around what a bidirectional "
                            "encoder actually does well, e.g. graph or candidate retrieval",
    },
    "roster": {
        "Lexi": "LFM2.5-230M causal",
        "Lepori": "MiniCPM5-1B-Base causal",
        "Encoder": "PARKED / preserved lineage",
    },
    "substrate": {
        "name": "openbmb/MiniCPM5-1B-Base",
        "model_root": r"D:\codex-runs\jev-zero-training-recon-v01\models\minicpm5-1b-base",
        "revision": "156170697656c48f69915b33a2fb44110242187c",
        "architectures": "LlamaForCausalLM",
        "model_type": "llama",
        "trust_remote_code": False,
        "parameters": 1080632832,
        "dtype": "bfloat16",
        "hidden_size": 1536,
        "num_hidden_layers": 24,
        "num_attention_heads": 16,
        "num_key_value_heads": 2,
        "intermediate_size": 4608,
        "frozen": True,
        "qualification_receipt": "substrate-qualification.json",
        "qualification_status": "SUBSTRATE_QUALIFIED",
    },
    "surfaces": {
        "validated_depth_layers": [6, 12, 18, 24],
        "depth_fractions": [0.25, 0.5, 0.75, 1.0],
        "convention": "hidden_states tuple of length num_hidden_layers+1; index 0 is the "
                      "embedding output and index i is decoder block i; index 0 never requested",
        "pooling": {
            "lt@24": "last real token at final depth -- the causal summary",
            "mf@24": "mean over all real tokens at final depth",
            "ms@24": "mean over the last 16 real tokens at final depth",
            "mf@18": "mean over all real tokens at 75% depth",
            "mf@12": "mean over all real tokens at 50% depth",
            "mf@6": "mean over all real tokens at 25% depth",
        },
        "per_surface_normalisation_required": True,
        "per_surface_normalisation_reason": "hidden scale varies ~6x with depth (std 3.73 at layer "
                                           "24 vs 23.59 at layer 18); unnormalised cross-surface "
                                           "mixing would let shallow surfaces dominate",
        "entity_spans": "mention char offsets resolved to token spans and mean-pooled at final "
                        "depth, where a causal mention representation is context-complete",
    },
    "candidate_contract": {
        "m_max": 28,
        "rule": "retain every canonical candidate",
        "ordering": "canonical available_actions order",
        "padding": "-1 entity indices, cand_type 0, mask 0",
        "padded_candidates": "excluded from every loss and metric",
        "max_args": 3,
    },
    "inherited_constraints": [
        "exhaustive candidates at the measured maximum, never a typed constant",
        "no raw latent-matching invariance loss; consistency on predictions via JS",
        "diversity is not competence; never report D_s as a success metric",
        "paired correctness decomposition instead of naked renderer agreement",
        "weight over independent canonical sources, never head count",
        "balanced BCE with TRAIN-only prevalence; selection on J_select; pre-registered margins",
        "no generic global-token/candidate-token recurrent mixer",
        "port the contract, not the encoder graft",
    ],
    "protected": {
        "PROTECTED_TEST_TRUTH_OPENED": False,
        "BANK_V2_USED": False,
        "CANONICAL_SPLITS": "BANK-v1 unchanged",
    },
}

OUT_DIR = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")
OUT_DIR.mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    p = OUT_DIR / "substrate-contract.json"
    p.write_text(json.dumps(CONTRACT, indent=2) + "\n")
    print(json.dumps({"written": str(p),
                      "substrate": CONTRACT["substrate"]["name"],
                      "params": CONTRACT["substrate"]["parameters"],
                      "depths": CONTRACT["surfaces"]["validated_depth_layers"],
                      "m_max": CONTRACT["candidate_contract"]["m_max"],
                      "constraints": len(CONTRACT["inherited_constraints"])}, indent=2))
