"""Revalidate live predicates wherever an issued capability is consumed."""
from .identity import strict_json
from .policy import evaluate


class GateOperations:
    def authorization_valid(self, identity, actor_id, run_id, stage_id):
        if not self.policy.authorization_valid(identity, actor_id, run_id, stage_id):
            return False
        if self.authority.actors.get(actor_id, {}).get("lab") != self.run_labs.get(run_id):
            return False
        current = self.policy.policies.get(stage_id)
        if current is None:
            return False
        policy = strict_json(self.cas.get(current["artifact_id"]))
        gpu = any(self.leases.resources[resource]["kind"] == "GPU"
                  and self.leases.leases[lease]["stage_id"] == stage_id
                  and self.leases.valid(lease, resource, self.leases.leases[lease]["fencing_token"], actor_id, run_id)
                  for resource, lease in self.leases.active.items())
        decision, _, _ = evaluate(policy, self.policy, self.authority, run_id, actor_id, stage_id, gpu)
        return decision == "AUTHORIZED"
