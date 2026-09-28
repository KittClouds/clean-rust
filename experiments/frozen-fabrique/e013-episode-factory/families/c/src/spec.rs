#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FamilySpec {
    pub id: &'static str,
    pub slug: &'static str,
    pub title: &'static str,
    pub requirement: &'static str,
}

pub const FAMILIES: [FamilySpec; 8] = [
    FamilySpec {
        id: "c.token-cursor",
        slug: "token_cursor",
        title: "incremental UTF-8 token cursor",
        requirement: "Return half-open byte spans for each Unicode-whitespace-separated token. Offsets count UTF-8 bytes, and the output is comma-separated start:end pairs.",
    },
    FamilySpec {
        id: "c.interval-index",
        slug: "interval_index",
        title: "interval overlap index",
        requirement: "For each half-open interval in input order, report its zero-based index when it overlaps the query interval. Touching endpoints do not overlap; the output is a comma-separated index list.",
    },
    FamilySpec {
        id: "c.graph-witness",
        slug: "graph_witness",
        title: "shortest graph witness",
        requirement: "Return a shortest directed path from the requested source to target. Break equal-length ties by choosing the lexicographically smallest full node sequence; return an empty byte string when no path exists.",
    },
    FamilySpec {
        id: "c.delta-codec",
        slug: "delta_codec",
        title: "signed delta varint codec",
        requirement: "Encode each signed integer as a zigzagged variable-length unsigned integer after differencing it from the previous value (starting at zero). Emit the concatenated bytes.",
    },
    FamilySpec {
        id: "c.parser-precedence",
        slug: "parser_precedence",
        title: "addition and multiplication parser",
        requirement: "Evaluate decimal integer expressions containing + and *. Multiplication binds more tightly than addition and operators associate left to right within each precedence level. Emit the decimal result.",
    },
    FamilySpec {
        id: "c.window-fold",
        slug: "window_fold",
        title: "complete sliding-window fold",
        requirement: "Emit the sum of every complete fixed-width sliding window, in order. Do not emit partial prefixes; values and sums use signed 64-bit integers.",
    },
    FamilySpec {
        id: "c.binary-frame",
        slug: "binary_frame",
        title: "length-prefixed binary frame reader",
        requirement: "Read one frame encoded as a tag byte, a little-endian u16 payload length, and exactly that many payload bytes. Return the payload only; malformed or trailing bytes produce an empty byte string.",
    },
    FamilySpec {
        id: "c.dependency-eval",
        slug: "dependency_eval",
        title: "unique transitive dependency listing",
        requirement: "For a directed acyclic dependency graph, report every transitive dependency of the requested node exactly once, sorted by numeric node id and excluding the requested node.",
    },
];

pub fn by_id(id: &str) -> Option<&'static FamilySpec> {
    FAMILIES.iter().find(|family| family.id == id)
}

pub fn repo_profile(repo_id: &str) -> Option<&'static str> {
    match repo_id {
        "e013-c-lexistream" => Some("ingestion pipeline maintains UTF-8 cursor offsets across source chunks"),
        "e013-c-segmental" => Some("segment query service stores compact half-open ranges in sorted blocks"),
        "e013-c-pathproof" => Some("workflow graph service reconstructs deterministic witness paths from packed adjacency"),
        "e013-c-bytework" => Some("wire ingestion service validates small binary frames without copying payloads"),
        _ => None,
    }
}

pub fn repository_ids() -> [&'static str; 4] {
    [
        "e013-c-lexistream",
        "e013-c-segmental",
        "e013-c-pathproof",
        "e013-c-bytework",
    ]
}
