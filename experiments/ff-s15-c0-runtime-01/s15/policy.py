"""The C0 policy language: signals, conditions, and their load-time checks.

A policy holds ordered escalation rules and ordered authority rules. Conditions are small JSON
trees over integer, string and boolean signals, evaluated with three-valued logic (TRUE, FALSE,
UNKNOWN) so that a missing observer output can never make a rule fire by accident:

    all   FALSE if any child is FALSE, else UNKNOWN if any is UNKNOWN, else TRUE (stops at the first FALSE)
    any   TRUE if any child is TRUE, else UNKNOWN if any is UNKNOWN, else FALSE (stops at the first TRUE)
    not   UNKNOWN stays UNKNOWN
    cmp   UNKNOWN when the signal is missing or has a different type from the value
    agree / disagree   compare the top labels of observers that answer the same contract

A rule matches only when its condition is TRUE. Nothing here uses floats.

Signals
    obs.<fact>              a fact from the observation (integer, string or boolean)
    actor                   the acting principal
    action.name             the proposed action (authority rules only)
    authority.granted       proposed action is in the granted list (authority rules only)
    authority.forbidden     proposed action is in the forbidden list (authority rules only)
    authority.flag.<name>   a boolean flag from the authority state (missing means false)
    <alias>.top_label       the observer's most probable label (SIMPLEX contracts)
    <alias>.top_ppm         its probability, integer ppm
    <alias>.margin_ppm      top minus second, integer ppm
    <alias>.p.<LABEL>       the probability of one label, integer ppm
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MISSING = object()
MAX_DEPTH = 8
MAX_NODES = 64
OPS = {"eq", "ne", "lt", "le", "gt", "ge"}
_ALIAS = re.compile(r"[a-z][a-z0-9_]{0,31}")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
RESERVED = {"obs", "actor", "action", "authority"}


class PolicyError(ValueError):
    """A policy or condition that cannot be trusted to run."""


@dataclass(frozen=True)
class Sig:
    kind: str  # obs | actor | action | granted | forbidden | flag | observer
    name: str = ""
    alias: str = ""
    field: str = ""  # top_label | top_ppm | margin_ppm | p
    label: str = ""
    vtype: str = "any"  # int | str | bool | any

    @property
    def neural(self) -> bool:
        return self.kind == "observer"


def parse_signal(text: str, observers: dict[str, dict]) -> Sig:
    """`observers` maps alias -> DecisionContract."""
    parts = text.split(".")
    head = parts[0]
    if text == "actor":
        return Sig("actor", vtype="str")
    if head == "obs" and len(parts) == 2 and _NAME.fullmatch(parts[1]):
        return Sig("obs", name=parts[1])
    if text == "action.name":
        return Sig("action", vtype="str")
    if text == "authority.granted":
        return Sig("granted", vtype="bool")
    if text == "authority.forbidden":
        return Sig("forbidden", vtype="bool")
    if head == "authority" and len(parts) == 3 and parts[1] == "flag" and _NAME.fullmatch(parts[2]):
        return Sig("flag", name=parts[2], vtype="bool")
    if head in observers and len(parts) >= 2:
        contract = observers[head]
        simplex = contract["output_schema"]["kind"] == "SIMPLEX"
        field_name = parts[1]
        if field_name in ("top_label", "top_ppm", "margin_ppm") and len(parts) == 2:
            if not simplex:
                raise PolicyError(f"{text}: {field_name} needs a SIMPLEX contract; {head} answers an independent multi-choice")
            return Sig("observer", alias=head, field=field_name, vtype="str" if field_name == "top_label" else "int")
        if field_name == "p" and len(parts) == 3:
            if parts[2] not in contract["output_schema"]["labels"]:
                raise PolicyError(f"{text}: {parts[2]!r} is not a label of {contract['name']}")
            return Sig("observer", alias=head, field="p", label=parts[2], vtype="int")
    raise PolicyError(f"unknown signal {text!r}")


@dataclass
class Reads:
    """What a condition reads, collected at load time."""

    aliases: set = field(default_factory=set)
    neural_signals: set = field(default_factory=set)
    signals: set = field(default_factory=set)
    has_agree: bool = False
    nodes: int = 0


def check_cond(cond: dict, observers: dict[str, dict], actions: set, stage: str, reads: Reads | None = None, depth: int = 0) -> Reads:
    """Validates a condition against the policy's observers; `stage` is "escalation" or "authority"."""
    reads = reads if reads is not None else Reads()
    reads.nodes += 1
    if depth > MAX_DEPTH or reads.nodes > MAX_NODES:
        raise PolicyError("condition is too large or too deeply nested")
    (kind, body), = cond.items()
    if kind in ("all", "any"):
        for child in body:
            check_cond(child, observers, actions, stage, reads, depth + 1)
    elif kind == "not":
        check_cond(body, observers, actions, stage, reads, depth + 1)
    elif kind in ("agree", "disagree"):
        for alias in body:
            if alias not in observers:
                raise PolicyError(f"{kind}: unknown observer alias {alias!r}")
        contracts = {observers[alias]["contract_id"] for alias in body}
        if len(contracts) != 1:
            raise PolicyError(f"{kind}: {sorted(body)} do not answer the same contract")
        if observers[body[0]]["output_schema"]["kind"] != "SIMPLEX":
            raise PolicyError(f"{kind}: needs a SIMPLEX contract")
        reads.aliases.update(body)
        reads.has_agree = True
    elif kind == "cmp":
        signal_text, op, value = body["signal"], body["op"], body["value"]
        sig = parse_signal(signal_text, observers)
        if stage == "escalation" and sig.kind in ("action", "granted", "forbidden"):
            raise PolicyError(f"{signal_text}: not available before an action is proposed")
        if sig.vtype == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise PolicyError(f"{signal_text}: compare with an integer")
            if sig.kind == "observer" and not 0 <= value <= 1_000_000:
                raise PolicyError(f"{signal_text}: ppm values are 0..1000000")
        elif sig.vtype in ("str", "bool"):
            if op not in ("eq", "ne"):
                raise PolicyError(f"{signal_text}: only eq/ne for {sig.vtype} signals")
            if sig.vtype == "str" and not isinstance(value, str) or sig.vtype == "bool" and not isinstance(value, bool):
                raise PolicyError(f"{signal_text}: wrong value type")
            if sig.kind == "observer" and value not in observers[sig.alias]["output_schema"]["labels"]:
                raise PolicyError(f"{signal_text}: {value!r} is not a label of {observers[sig.alias]['name']}")
            if sig.kind == "action" and value not in actions:
                raise PolicyError(f"{signal_text}: {value!r} is not in the action catalogue")
        else:  # obs facts
            if op not in ("eq", "ne") and (isinstance(value, bool) or not isinstance(value, int)):
                raise PolicyError(f"{signal_text}: ordering operators need an integer")
        reads.signals.add(signal_text)
        if sig.neural:
            reads.aliases.add(sig.alias)
            reads.neural_signals.add(signal_text)
    else:  # pragma: no cover - the schema admits no other key
        raise PolicyError(f"unknown condition {kind!r}")
    return reads


def top_level_children(cond: dict) -> list[dict]:
    return cond["all"] if "all" in cond else []


def compare(op: str, left, right):
    """TRUE/FALSE, or None (UNKNOWN) when the types do not line up."""
    if isinstance(left, bool) != isinstance(right, bool) or type(left) is not type(right):
        return None
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if isinstance(left, bool) or not isinstance(left, int):
        return None
    return {"lt": left < right, "le": left <= right, "gt": left > right, "ge": left >= right}[op]
