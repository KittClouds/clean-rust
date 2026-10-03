# Frizz Qwen BANK-v3-core bridge

Verified fixed eighth-epoch endpoint. SYNTHETIC_ONLY; no evaluation files opened. E has not started.

## Production head

- candidate_satisfies_goal: init 0.587391; trained 0.747920; delta +0.160528.
- candidate_legal: init 0.526428; trained 0.804245; delta +0.277817.

Exact named-candidate and optimal-set endpoints (canonical roots):

{
  "exact_logged_action": {
    "n": 333,
    "correct": 30,
    "accuracy": 0.09009008854627609
  },
  "optimal_set_hit": {
    "n": 333,
    "hits": 30,
    "rate": 0.09009008854627609
  },
  "exact_logged_on_optimal_subset": {
    "n": 333,
    "accuracy": 0.09009008854627609
  },
  "empty_optimal_roots": 2667,
  "by_logged_action_type": {
    "MOVE": {
      "n": 249,
      "correct": 27,
      "accuracy": 0.10843373493975904,
      "reliable": true,
      "claim": "eligible"
    },
    "TAKE": {
      "n": 39,
      "correct": 3,
      "accuracy": 0.07692307692307693,
      "reliable": false,
      "claim": "SUPPORT_ONLY_UNDERPOWERED"
    },
    "DEACTIVATE": {
      "n": 5,
      "correct": 0,
      "accuracy": 0.0,
      "reliable": false,
      "claim": "SUPPORT_ONLY_UNDERPOWERED"
    },
    "OPEN": {
      "n": 11,
      "correct": 0,
      "accuracy": 0.0,
      "reliable": false,
      "claim": "SUPPORT_ONLY_UNDERPOWERED"
    },
    "ACTIVATE": {
      "n": 10,
      "correct": 0,
      "accuracy": 0.0,
      "reliable": false,
      "claim": "SUPPORT_ONLY_UNDERPOWERED"
    },
    "DROP": {
      "n": 14,
      "correct": 0,
      "accuracy": 0.0,
      "reliable": false,
      "claim": "SUPPORT_ONLY_UNDERPOWERED"
    },
    "CLOSE": {
      "n": 4,
      "correct": 0,
      "accuracy": 0.0,
      "reliable": false,
      "claim": "SUPPORT_ONLY_UNDERPOWERED"
    },
    "WAIT": {
      "n": 1,
      "correct": 0,
      "accuracy": 0.0,
      "reliable": false,
      "claim": "SUPPORT_ONLY_UNDERPOWERED"
    }
  }
}

Only MOVE meets the 200-root DEV action-type floor. Other types are support-only. Conflict and counterevidence axes are diagnostic; restricted targets require strata. No composite capability score. v1-v3 comparisons are not matched mechanism effects.

All recorder outputs: baseline/receipt.json, readouts/*.json, bridge-verification.json. Positive controls pass; exact same-code fresh-process replay passes.

Engineering decisions: accepted separator repair; full-context extraction rather than 512-token truncation; four arguments and nine action types; exhaustive candidate masking; fixed epoch selection; TRAIN-only normalization/prevalence/pairs. Preparation v01 failed before feature output on a missing Path import and is preserved.
