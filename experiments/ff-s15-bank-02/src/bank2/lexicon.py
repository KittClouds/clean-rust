"""Bank-owned vocabulary pools. SEEN/HELD membership is a hash partition of each word, so TEST-VOCAB's holdout is a structural predicate, not a list someone curated."""
from __future__ import annotations

from .canon import sha256_hex

LOCATIONS = """hall cellar attic garden kitchen library pantry balcony cloister workshop tower chapel armory foyer
study loft dock orchard vault gallery laboratory greenhouse stable courtyard crypt observatory
market bridge tunnel lobby annex harbor quarry mill shrine terrace nursery archive""".split()
OBJECTS = """key lantern book coin rope compass map ledger flask hammer candle scroll badge mirror bell
feather ring satchel helmet wrench spool crystal whistle dagger chalice ribbon locket pouch anvil tablet
kettle needle brush beacon gauge magnet relic token lens ticket plank prism chisel valve mallet
pendant parcel bottle lever-arm gear spindle canister""".split()
CONTAINERS = """chest crate basket locker cabinet trunk casket hamper cupboard barrel drawer coffer""".split()
SWITCHES = """lever dial switch valve-wheel pedal crank button toggle panel knob latch-plate beacon-switch""".split()
AGENTS = """Ada Bo Cyr Dara Eli Fen Gus Hana Ivo Jun Kiri Lev Mara Nico Odel Pia Quin Rafe Sera Tovi Una Vik Wren Xan""".split()
ADJECTIVES = """red blue green brass iron copper silver old new small large wooden glass narrow quiet bright dull heavy light
dusty polished cracked painted folded sealed woven""".split()
AMBIG_ADJ = ["dim", "odd", "plain", "twin", "faint", "stray", "bare", "fair", "cold", "warm", "tall", "low"]
ADJ_FOR_ALIAS = ADJECTIVES


def is_held(word: str) -> bool:
    return int(sha256_hex("bank2-lexicon|" + word)[:8], 16) % 4 == 0  # 25% held


def pool(words: list[str], held: bool) -> list[str]:
    return [w for w in words if is_held(w) == held]


KIND_POOLS = {"LOCATION": LOCATIONS, "OBJECT": OBJECTS, "CONTAINER": CONTAINERS, "SWITCH": SWITCHES, "AGENT": AGENTS}
TYPE_NOUN = {"LOCATION": "place", "OBJECT": "item", "CONTAINER": "container", "SWITCH": "device", "AGENT": "person"}


def names_for(kind: str, held: bool) -> list[str]:
    return pool(KIND_POOLS[kind], held)


def all_words() -> set:
    return {w for ws in KIND_POOLS.values() for w in ws} | set(ADJECTIVES) | set(AMBIG_ADJ)
