# Chief Kammi bookkeeping handoff v1

Effective: 2026-09-27. Authority: the user's instruction in Chief Kammi.
Owner: Chief Kammi, Lab Chief and Head Librarian.

## Operating rule

Agents perform their assigned scientific, engineering, product, or construction work.
They hand their artifacts and execution observations to Chief Kammi.
Chief owns program bookkeeping and uses Kammi Ledger on their behalf.
Library implementation and custody vocabulary remain centrally maintained.

This rule applies to the Kammi program and its participating labs and agents.
It changes administrative ownership. Existing scientific ownership, sealed protocols,
access restrictions, stops, and authorization requirements remain in force.

## Responsibilities

| Responsibility | Owner |
| --- | --- |
| Hypotheses, task design, implementation, authorized execution, analysis | Assigned lab/agent |
| Scientific tests, executable adjudicators, raw logs and outputs | Assigned lab/agent |
| Artifact ingestion, identities, CAS, lineage, seals, authoritative heads | Chief Kammi |
| Authorization records, grants, exposure accounting, fenced resource leases | Chief Kammi through the Library service |
| Attempt history, contact accounting, failures, remote evidence reconciliation | Chief Kammi |
| Institutional memory intake, evidence links, retrieval handoffs | Chief Kammi |
| Library code, adapters, migrations, custody vocabulary, qualification | Chief Kammi / centrally assigned Library maintenance |
| Scientific interpretation, result claims, protocol amendments | Originating lab with its existing authorization process |

Lab agents do not create a local custody system, write bespoke provenance validators,
operate the ledger daemon, edit library schemas, access Ladybug directly, or perform
manual ledger/SDK/MCP bookkeeping. They request those services from Chief.
An infrastructure problem is reported to Chief; the agent preserves its work and
continues any authorized independent work that does not depend on the problem.

## Minimal handoff

Use ordinary language and existing artifacts. No new lab-specific receipt schema is
required. Supply only what is available from the work itself:

```text
To: Chief Kammi — bookkeeping handoff
Lab / task / current stage:
Existing instruction or authorization reference, if any:
What changed or completed:
Artifact paths / repository commit / existing manifest:
What ran, and where the raw logs are:
Observed contacts or evidence openings; uncertainty if tracking is incomplete:
Failure, stop, or next gated action:
Resource need, if a new lease is required:
Protected material: classification and location only until access is authorized.
```

Point to an existing manifest instead of reconstructing its contents. Agents do not
rehash whole ancestors, flatten seal closures, rename historical receipt fields,
or generate fresh contracts to accommodate bookkeeping machinery.
Chief computes and checks identities. Locally generated hashes remain supporting
information until verified. Missing observations are recorded as unknown.

## Chief's intake and return loop

1. Identify the originating lab, current task, existing authority, and artifact class.
2. Preserve exact bytes and failed attempts. Ingest only material Chief is authorized
   to access. Do not open protected panels or hidden fixtures merely to catalogue them.
3. Register immutable objects and their derivation; reconcile attempts, contacts,
   exposure purpose, supersession, and head claims against cited evidence.
4. Apply existing policy, adapter, and resource rules. Register raw evidence before
   making custody assertions. Report unknowns and discrepancies explicitly.
5. Construct or verify seals using direct members and parent roots. Keep scientific,
   execution, and toolchain identity separate.
6. Return a concise custody disposition: recorded, verified, or pending, with exact
   references and any actual gated dependency. Bookkeeping completion does not imply
   scientific eligibility or result promotion.
7. Record contextual memory separately, with custody references when grounded.

Chief may perform cross-lab custody review. Each lab's inputs, splits, seeds,
results, and scientific claims retain their original ownership. Shared code never
turns one lab's evidence into another lab's evidence.

## Before a gated operation

For a new run, resource acquisition, protected evidence opening, model contact,
remote dispatch, or result promotion, the agent sends the intended operation to Chief
before performing it when its existing protocol requires authorization.

Chief prepares and records the required scoped authority and fenced lease, then
returns the permitted execution handoff. Approved runner instrumentation captures
actual launches, contacts, openings, lease checks, and outputs automatically;
Chief reconciles those observations. Agents do not invent or manually maintain the
underlying custody events. A requested action is not permission to execute it.

Protected evidence must remain behind its authorized gateway. A lease must remain
valid during execution and remote return. Plaintext credentials stay out of reports
and handoffs. Central bookkeeping does not permit retrospective authorization.

## Transition

- Effective immediately for new bookkeeping requests and future work boundaries.
- Already authorized running work keeps its current contract and instrumentation.
  Do not interrupt a valid run merely to rewrite administrative artifacts.
- At the next natural checkpoint, hand existing outputs, manifests, and logs to Chief.
- Preserve existing immutable seals and failure history. Chief imports history without
  turning historical assertions into current permission.
- Stop producing redundant local custody wrappers. Keep logs and scientific verifiers
  that the experiment actually needs.
- Paused, stopped, and design-only work retains that state. This notice starts no run,
  reopens no scientific gate, and authorizes no observer contact.
- New agents receive this plan during onboarding. Chief maintains the distribution
  record and coordinates future Library requests.

## Rollout and verification

Chief distributes this notice to the participating program chats, records delivery
outcomes, and receives administrative handoffs at their normal checkpoints. Delivery
is distinct from acknowledgement and migration. No lab owes a new protocol or a
bookkeeping implementation as its response.

The next genuine handoff from each lab is used to check that the agent can deliver
its work with a short pointer-based handoff and receive a custody disposition from
Chief. No scientific experiment is run just to demonstrate this administrative change.

The objective is simple: agents produce their work; Chief records how it came to exist.
