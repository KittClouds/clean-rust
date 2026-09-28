"""Generic live attempts and result heads, separate from historical assertions."""
from .graph import SAFE


class LifecycleState:
    def __init__(self):
        self.attempts = {}
        self.heads = {}

    def apply(self, kind, payload, event_id):
        if kind == "AttemptStarted":
            if payload["attempt_id"] in self.attempts:
                raise ValueError("duplicate attempt identity")
            self.attempts[payload["attempt_id"]] = {**payload, "state": "RUNNING", "events": [event_id]}
        elif kind in {"AttemptStopped", "AttemptCompleted"}:
            attempt = self.attempts[payload["attempt_id"]]
            if attempt["state"] != "RUNNING":
                raise ValueError("attempt already terminal")
            attempt.update({**payload, "state": "STOPPED" if kind == "AttemptStopped" else "COMPLETE",
                            "events": [*attempt["events"], event_id]})
        elif kind == "ResultDeclared":
            self.heads[(payload["run_id"], payload["stage_id"])] = {**payload, "event_id": event_id}


class LifecycleOperations:
    def start_attempt(self, attempt_id, run_id, stage_id, actor_id, authorization_id, request_id):
        with self.lock:
            if not SAFE.fullmatch(attempt_id) or not self.authorization_valid(
                authorization_id, actor_id, run_id, stage_id
            ):
                raise ValueError("attempt lacks current scoped authorization")
            return self._emit("AttemptStarted", {"attempt_id": attempt_id, "run_id": run_id,
                              "stage_id": stage_id, "actor_id": actor_id,
                              "authorization_id": authorization_id}, actor_id, request_id)

    def finish_attempt(self, attempt_id, actor_id, outcome, evidence_artifact, reason, request_id):
        if outcome not in {"STOPPED", "COMPLETE"} or not reason or len(reason) > 4096:
            raise ValueError("invalid attempt outcome")
        with self.lock:
            attempt = self.lifecycle.attempts.get(attempt_id)
            if attempt is None or attempt["actor_id"] != actor_id or evidence_artifact not in self.artifacts:
                raise ValueError("attempt/evidence/actor mismatch")
            if request_id in self.journal.by_request:
                prior, identity = self.journal.by_request[request_id]
                from .identity import strict_json
                payload = strict_json(self.cas.get(prior["payload_artifact"]))
                if payload["attempt_id"] != attempt_id or payload["evidence_artifact"] != evidence_artifact or payload["reason"] != reason:
                    raise ValueError("attempt request ID reused")
                return identity
            if attempt["state"] != "RUNNING":
                raise ValueError("attempt already terminal")
            return self._emit("AttemptStopped" if outcome == "STOPPED" else "AttemptCompleted",
                              {"attempt_id": attempt_id, "run_id": attempt["run_id"],
                               "stage_id": attempt["stage_id"], "actor_id": actor_id,
                               "evidence_artifact": evidence_artifact, "reason": reason}, actor_id, request_id)

    def declare_result(self, run_id, stage_id, actor_id, authorization_id, seal_root, predecessor, request_id):
        with self.lock:
            if not self.authorization_valid(authorization_id, actor_id, run_id, stage_id):
                raise ValueError("result lacks current authorization")
            self.verify_seal(seal_root)
            prior = self.lifecycle.heads.get((run_id, stage_id))
            expected = prior["seal_root"] if prior else None
            if request_id not in self.journal.by_request and predecessor != expected:
                raise ValueError("result predecessor is not current head")
            return self._emit("ResultDeclared", {"run_id": run_id, "stage_id": stage_id,
                              "actor_id": actor_id, "authorization_id": authorization_id,
                              "seal_root": seal_root, "predecessor": predecessor}, actor_id, request_id)
