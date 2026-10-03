"""E4-0 sealed row-stream and generic stage-artifact seal primitives."""

from e4_runner_common_v04 import *  # noqa: F401,F403

def input_row_stream(path: Path, manifest_path: Path) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    expected_input_keys = {"row_id", "quartet_id", "variant_id", "input_text"}
    expected_manifest_keys = {"row_index", "row_id", "quartet_id", "variant_id", "surface_id", "truth_partition"}
    sentinel = object()
    for index, pair in enumerate(zip_longest(iter_jsonl(path), iter_jsonl(manifest_path), fillvalue=sentinel)):
        input_row, manifest = pair
        if input_row is sentinel or manifest is sentinel:
            raise E4RunnerError("population model inputs and row manifest have different lengths")
        if set(input_row) != expected_input_keys:
            raise E4RunnerError("population model input has extra fields or a label")
        if set(manifest) != expected_manifest_keys:
            raise E4RunnerError("population row manifest differs from the label-free E4 schema")
        if type(manifest["row_index"]) is not int or manifest["row_index"] != index:
            raise E4RunnerError("population row index differs from its sealed manifest order")
        if any(not isinstance(input_row[key], str) or not input_row[key] for key in ("row_id", "quartet_id", "variant_id", "input_text")):
            raise E4RunnerError("population input identity/text fields must be nonempty strings")
        if any(not isinstance(manifest[key], str) or not manifest[key] for key in (
            "row_id", "quartet_id", "variant_id", "surface_id", "truth_partition",
        )):
            raise E4RunnerError("population manifest identity/custody fields must be nonempty strings")
        for key in ("row_id", "quartet_id", "variant_id"):
            if input_row[key] != manifest[key]:
                raise E4RunnerError(f"population row identity mismatch: {key}")
        surface = manifest["surface_id"]
        custody = manifest["truth_partition"]
        if (surface, custody) not in ((PRIMARY_SURFACE, PRIMARY_CUSTODY), (HELDOUT_SURFACE, ESCROW_CUSTODY)):
            raise E4RunnerError("population row custody/surface is outside the frozen two-partition schema")
        yield input_row, manifest


def iter_validated_e4_rows(
    rows: Iterable[tuple[dict[str, Any], dict[str, Any]]],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    iterator = iter(rows)
    seen_quartets: set[str] = set()
    seen_rows: set[str] = set()
    for ordinal in range(E4_QUARTETS):
        try:
            group = [next(iterator) for _ in range(8)]
        except StopIteration as error:
            raise E4RunnerError("E4 population ended before the frozen 18,667 paired quartets") from error
        expected = [(PRIMARY_SURFACE, variant) for variant in VARIANTS] + [(HELDOUT_SURFACE, variant) for variant in VARIANTS]
        quartet_ids: set[str] = set()
        for local_index, ((input_row, manifest), (expected_surface, expected_variant)) in enumerate(zip(group, expected)):
            if manifest["surface_id"] != expected_surface or manifest["variant_id"] != expected_variant:
                raise E4RunnerError("E4 rows are not schedule-ordered primary/heldout A,C,E,P")
            quartet_ids.add(str(manifest["quartet_id"]))
            row_id = str(manifest["row_id"])
            if row_id in seen_rows:
                raise E4RunnerError("E4 row ID repeats within the sealed population")
            seen_rows.add(row_id)
            if local_index < 4 and manifest["truth_partition"] != PRIMARY_CUSTODY:
                raise E4RunnerError("primary E4 rows are not marked PRIMARY_TERMINAL")
            if local_index >= 4 and manifest["truth_partition"] != ESCROW_CUSTODY:
                raise E4RunnerError("held-out E4 rows are not marked TEMPLATE_ESCROW")
            if input_row["row_id"] != row_id:
                raise E4RunnerError("E4 row identity changed during ordered preflight")
        if len(quartet_ids) != 1:
            raise E4RunnerError(f"paired surfaces do not share one semantic quartet at ordinal {ordinal}")
        quartet_id = next(iter(quartet_ids))
        if quartet_id in seen_quartets:
            raise E4RunnerError("E4 semantic quartet ID repeats at a new schedule ordinal")
        seen_quartets.add(quartet_id)
        yield from group
    try:
        next(iterator)
    except StopIteration:
        return
    raise E4RunnerError("E4 population contains rows beyond the frozen prefix")


def validate_e4_order(rows: Iterable[tuple[dict[str, Any], dict[str, Any]]]) -> None:
    for _ in iter_validated_e4_rows(rows):
        pass


def verify_population_rows_before_model(authorization: Mapping[str, Any]) -> None:
    names = ("population_inputs", "population_rows")
    verify_bound_artifacts(authorization, names)
    inputs = Path(authorization["artifacts"]["population_inputs"]["path"])
    rows = Path(authorization["artifacts"]["population_rows"]["path"])
    validate_e4_order(input_row_stream(inputs, rows))


def verify_predecessor_audits(authorization: Mapping[str, Any], mode: str) -> None:
    names = ["e1_audit", "e2_audit", "e3_audit"]
    if mode in ("parity", "extract-e4"):
        names.extend(("population_seal", "population_audit"))
    if mode == "parity":
        names.append("parity_panel_seal")
    if mode == "extract-e4":
        names.extend(("parity_panel_seal", "parity_receipt_seal"))
    artifacts = verify_bound_artifacts(authorization, names)
    expected = {
        "e1_audit": ("status", "PASS", "e1_root_sha256", E1_ROOT),
        "e2_audit": ("status", "E2_V07_INDEPENDENT_AUDIT_PASS_E3_NOT_AUTHORIZED_BY_E0_FREEZE", "e2_root_sha256", E2_ROOT),
        "e3_audit": ("status", "E3_V02_FIVE_FITS_INDEPENDENT_AUDIT_PASS_HELDOUT_SCORING_CLOSED", "e3_root_sha256", E3_BUNDLE_ROOT),
    }
    for name, (status_key, status_value, root_key, root_value) in expected.items():
        receipt = read_json(Path(artifacts[name]["path"]))
        if receipt.get(status_key) != status_value or receipt.get(root_key) != root_value:
            raise E4RunnerError(f"independent predecessor audit is absent or mismatched: {name}")
    if mode == "extract-e4":
        expected_root = authorization["exact_predecessor_roots"]["e4_population_root_sha256"]
    else:
        expected_root = authorization["exact_predecessor_roots"]["e4_population_root_sha256"]
    population_seal = verify_stage_seal(
        Path(artifacts["population_seal"]["path"]), expected_root, "POPULATION_GENERATION",
        authorization,
    )
    population_audit = read_json(Path(artifacts["population_audit"]["path"]))
    audit_sha = artifacts["population_audit"]["sha256"]
    if authorization["exact_predecessor_roots"].get("e4_population_audit_root_sha256") != audit_sha:
        raise E4RunnerError("E4 population audit receipt hash differs from its bound root")
    if population_audit.get("population_root_sha256") != expected_root or "PASS" not in str(population_audit.get("status", "")).upper():
        raise E4RunnerError("E4 population independent audit did not pass")
    if population_seal["root_sha256"] != population_audit.get("population_root_sha256"):
        raise E4RunnerError("population audit does not independently bind the sealed population")
    if mode in ("parity", "extract-e4"):
        panel_root = authorization["exact_predecessor_roots"]["e4_parity_panel_root_sha256"]
        verify_stage_seal(Path(artifacts["parity_panel_seal"]["path"]), panel_root, "PARITY_PANEL_MATERIALIZATION", authorization)
    if mode == "extract-e4":
        parity_root = authorization["exact_predecessor_roots"]["e4_parity_receipt_root_sha256"]
        parity_seal = verify_stage_seal(Path(artifacts["parity_receipt_seal"]["path"]), parity_root, "ONLINE_CACHE_PARITY", authorization)
        receipt_entry = next((item for item in parity_seal["entries"] if item.get("artifact_id") == "parity_receipt"), None)
        if receipt_entry is None:
            raise E4RunnerError("parity seal does not contain a parity receipt")
        parity_receipt_path = Path(authorization["output_root"]).resolve() / receipt_entry["path"]
        parity_receipt = read_json(parity_receipt_path)
        if parity_receipt.get("status") != "ONLINE_CACHE_PARITY_PASS":
            raise E4RunnerError("passing online/cache parity receipt is absent")


def stage_output_root(authorization: Mapping[str, Any], mode: str) -> Path:
    stage_dir = {
        "parity": "parity",
        "extract-e4": "features",
    }[mode]
    return Path(authorization["output_root"]).resolve() / stage_dir


def artifact_root(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda value: str(value["artifact_id"]).encode("utf-8")):
        line = f'{entry["artifact_id"]}\t{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def seal_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def verify_stage_seal(
    path: Path,
    expected_root: str,
    expected_stage: str,
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    seal = read_json(path)
    if seal.get("schema") != "FAS_E4_0_ARTIFACT_SEAL_V01" or seal.get("status") != "SEALED" or seal.get("stage") != expected_stage:
        raise E4RunnerError(f"stage seal identity mismatch: {path}")
    if seal.get("path_root_kind") != "E4_RUN_ROOT":
        raise E4RunnerError("post-contract stage seal path root is not E4_RUN_ROOT")
    inherited_v06 = expected_stage in ("POPULATION_GENERATION", "PARITY_PANEL_MATERIALIZATION")
    expected_contract_sha = INHERITED_E4_V06_CONTRACT_SHA256 if inherited_v06 else authorization.get("contract_sha256")
    expected_contract_root = INHERITED_E4_V06_CONTRACT_ROOT if inherited_v06 else authorization.get("contract_seal_root_sha256")
    expected_seal_id = f"FAS_FROZEN_CAPABILITY_FABRIC_E4_0_{expected_stage}_SEAL_V01"
    if seal.get("seal_id") != expected_seal_id:
        raise E4RunnerError("stage seal ID differs from its registered stage identity")
    if seal.get("contract_sha256") != expected_contract_sha:
        raise E4RunnerError("stage seal does not bind the exact E4-0 contract bytes")
    if seal.get("contract_seal_root_sha256") != expected_contract_root:
        raise E4RunnerError("stage seal does not bind the E4-0 contract seal root")
    entries = seal.get("entries")
    if not isinstance(entries, list) or not entries:
        raise E4RunnerError("stage seal does not contain a nonempty entry list")
    if any(not isinstance(entry, dict) or set(entry) != {"artifact_id", "path", "bytes", "sha256"} for entry in entries):
        raise E4RunnerError("stage seal member schema differs from the normative schema")
    if any(
        type(entry["bytes"]) is not int or entry["bytes"] < 0
        or not isinstance(entry["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
        for entry in entries
    ):
        raise E4RunnerError("stage seal member byte length or digest is malformed")
    if type(seal.get("entry_count")) is not int or seal["entry_count"] != len(entries):
        raise E4RunnerError("stage seal entry count differs from its entry list")
    if seal.get("root_sha256") != expected_root:
        raise E4RunnerError("stage seal root or entry count mismatch")
    if artifact_root(entries) != expected_root:
        raise E4RunnerError("stage seal root failed independent recomputation")
    base_root = Path(authorization["output_root"]).resolve(strict=True)
    ids: set[str] = set()
    paths: set[str] = set()
    for entry in entries:
        artifact_id = entry.get("artifact_id")
        relative = entry.get("path")
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in ids:
            raise E4RunnerError("stage seal has an empty or duplicate artifact ID")
        if not isinstance(relative, str) or "\\" in relative or "\t" in relative or "\n" in relative:
            raise E4RunnerError("stage seal member path is not a safe relative POSIX path")
        parts = relative.split("/")
        if not relative or relative.startswith("/") or any(part in ("", ".", "..") for part in parts):
            raise E4RunnerError("stage seal member path is not rooted under the E4-0 run directory")
        if relative in paths:
            raise E4RunnerError("stage seal contains duplicate member paths")
        ids.add(artifact_id)
        paths.add(relative)
        file_identity(base_root.joinpath(*parts), entry["sha256"], int(entry["bytes"]))
    if set(seal) != {
        "schema", "status", "seal_id", "stage", "path_root_kind", "created_utc", "contract_sha256",
        "contract_seal_root_sha256", "exact_predecessor_roots", "entries", "entry_count", "root_sha256",
    }:
        raise E4RunnerError("stage seal top-level schema differs from the normative schema")
    seal_roots = seal.get("exact_predecessor_roots")
    authorized_roots = authorization.get("exact_predecessor_roots")
    if not isinstance(seal_roots, dict) or not isinstance(authorized_roots, dict):
        raise E4RunnerError("stage seal or authorization omits exact predecessor roots")
    if any(authorized_roots.get(key) != value for key, value in seal_roots.items()):
        raise E4RunnerError("stage seal predecessor roots differ from authorization")
    if inherited_v06 and any(
        seal_roots.get(key) != value
        for key, value in {
            "e0_v10_root_sha256": E0_ROOT,
            "e1_v04_root_sha256": E1_ROOT,
            "e2_v07_root_sha256": E2_ROOT,
            "e3_v02_bundle_root_sha256": E3_BUNDLE_ROOT,
        }.items()
    ):
        raise E4RunnerError("inherited v06 stage does not bind the exact frozen E0-E3 roots")
    return seal


def write_stage_seal(authorization: Mapping[str, Any], stage: str, output_root: Path, artifact_paths: Mapping[str, Path]) -> dict[str, Any]:
    run_root = Path(authorization["output_root"]).resolve(strict=True)
    entries = []
    for artifact_id, path in artifact_paths.items():
        absolute = path.resolve(strict=True)
        try:
            relative = absolute.relative_to(run_root).as_posix()
        except ValueError as error:
            raise E4RunnerError(f"stage artifact escapes the E4-0 run root: {absolute}") from error
        digest, size = sha256_file(path)
        entries.append({"artifact_id": artifact_id, "path": relative, "bytes": size, "sha256": digest})
    if not entries:
        raise E4RunnerError("stage seal cannot be empty")
    if len({entry["path"] for entry in entries}) != len(entries):
        raise E4RunnerError("stage seal cannot bind one artifact path under multiple IDs")
    root = artifact_root(entries)
    seal = {
        "schema": "FAS_E4_0_ARTIFACT_SEAL_V01",
        "status": "SEALED",
        "seal_id": f"FAS_FROZEN_CAPABILITY_FABRIC_E4_0_{stage}_SEAL_V01",
        "stage": stage,
        "path_root_kind": "E4_RUN_ROOT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": authorization["contract_sha256"],
        "contract_seal_root_sha256": authorization["contract_seal_root_sha256"],
        "exact_predecessor_roots": authorization["exact_predecessor_roots"],
        "entries": sorted(entries, key=lambda item: item["artifact_id"].encode("utf-8")),
        "entry_count": len(entries),
        "root_sha256": root,
    }
    path = output_root / "stage-seal-v01.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb", buffering=0) as stream:
        stream.write(seal_json_bytes(seal))
        os.fsync(stream.fileno())
    return seal


def read_numpy_cache(path: Path, rows: int, expected_sha256: str, expected_bytes: int, np: Any) -> Any:
    digest, size = sha256_file(path)
    if digest != expected_sha256 or size != expected_bytes:
        raise E4RunnerError("sealed feature cache hash/length differs from the authorized identity")
    if size != rows * FEATURE_ROW_BYTES:
        raise E4RunnerError("sealed feature cache size differs from explicit rows x dimension x dtype")
    return np.memmap(path, dtype="<f4", mode="r", shape=(rows, DIMENSION), order="C")


def verified_contract_root(authorization: Mapping[str, Any]) -> str:
    return str(authorization["contract_seal_root_sha256"])


def load_authorization(path: Path) -> dict[str, Any]:
    value = read_json(path)
    value["authorization_path"] = str(path.resolve(strict=True))
    value["authorization_sha256"] = sha256_file(path)[0]
    return value
