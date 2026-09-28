from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
RUN = ROOT / "artifacts" / "runs" / "e009-20260925-expanded-01"
OUTPUT = ROOT / "models" / "chat-templates"
OUTPUT.mkdir(parents=True, exist_ok=True)

entries = []
for role, bundle_id, expected_alias in (
    ("small", "minicpm5-2b-q8-local-v3", "e009-small-v3"),
    ("large", "ternary-bonsai-2-27b-ptq1-local-v3", "e009-large-v3"),
):
    props_path = RUN / role / "runtime-props.json"
    props = json.loads(props_path.read_text(encoding="utf-8-sig"))
    if props.get("model_alias") != expected_alias:
        raise SystemExit(f"runtime properties alias mismatch for {role}")
    template = props.get("chat_template")
    if not isinstance(template, str) or not template:
        raise SystemExit(f"runtime did not expose a chat template for {role}")
    path = OUTPUT / f"{bundle_id}.jinja"
    data = template.encode("utf-8")
    path.write_bytes(data)
    entries.append(
        {
            "role": role,
            "bundle_id": bundle_id,
            "chat_template_id": f"{props['model_alias']}:{props['build_info']}:model-embedded",
            "chat_template_sha256": hashlib.sha256(data).hexdigest(),
            "chat_template_bytes": len(data),
            "chat_format": props["default_generation_settings"]["params"]["chat_format"],
            "reasoning_format": props["default_generation_settings"]["params"]["reasoning_format"],
            "reasoning_in_content": props["default_generation_settings"]["params"]["reasoning_in_content"],
            "runtime_build_info": props["build_info"],
            "props_file_sha256": hashlib.sha256(props_path.read_bytes()).hexdigest(),
            "template_path": str(path),
        }
    )

receipt = {"schema_version": 1, "run_id": RUN.name, "templates": entries}
receipt_path = OUTPUT / "capture-receipt.json"
receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps(receipt, indent=2))
