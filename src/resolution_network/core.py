"""Inspectable support-pack build, local registry, and activation primitives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SHA = re.compile(r"[0-9a-f]{40}")
MAX_FILE = 2_000_000


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError("JSON file missing, linked, or too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _engine():
    try:
        from resolution_engine.engine import validate_knowledge
        from resolution_engine.evaluate import evaluate
    except ImportError:
        raise RuntimeError("install the pinned a2z-resolution-engine source before building packs") from None
    return validate_knowledge, evaluate


def validate_manifest(manifest: dict) -> None:
    required = {"schema_version", "id", "version", "title", "maintainer", "license",
                "evidence_class", "engine_source_commit"}
    if set(manifest) != required or manifest["schema_version"] != 1:
        raise ValueError("manifest fields or schema version invalid")
    if not isinstance(manifest["id"], str) or not SLUG.fullmatch(manifest["id"]):
        raise ValueError("pack id must be a lowercase slug")
    if not isinstance(manifest["version"], str) or not VERSION.fullmatch(manifest["version"]):
        raise ValueError("version must be numeric MAJOR.MINOR.PATCH")
    if not all(isinstance(manifest[k], str) and 1 <= len(manifest[k]) <= 160
               for k in ("title", "maintainer", "license")):
        raise ValueError("title, maintainer, and license required")
    if manifest["evidence_class"] != "SYNTHETIC_ONLY":
        raise ValueError("public pack format accepts synthetic cases only")
    if not isinstance(manifest["engine_source_commit"], str) or not SHA.fullmatch(manifest["engine_source_commit"]):
        raise ValueError("full engine source commit required")


def validate_payload(manifest: dict, knowledge: dict, suite: dict) -> dict:
    validate_manifest(manifest)
    validate_knowledge, evaluate = _engine()
    approved = validate_knowledge(knowledge, datetime.now(UTC).date())
    if not approved:
        raise ValueError("pack has no currently approved knowledge")
    cases = suite.get("cases") if isinstance(suite, dict) else None
    if not isinstance(cases, list) or len(cases) < 3:
        raise ValueError("at least three synthetic replay cases required")
    locales = {case.get("ticket", {}).get("locale") for case in cases if isinstance(case, dict)
               and isinstance(case.get("ticket"), dict)}
    if locales != {"ar", "en"}:
        raise ValueError("replay suite must cover English and Arabic")
    expected = {(case.get("expected_decision"), case.get("ticket", {}).get("locale"))
                for case in cases if isinstance(case, dict) and isinstance(case.get("ticket"), dict)}
    if not {("answer", "en"), ("answer", "ar")}.issubset(expected) or not any(x[0] == "escalate" for x in expected):
        raise ValueError("both language answers and an escalation case required")
    report = evaluate(knowledge, suite)
    if report["correct_against_declared_labels"] != report["cases"]:
        raise ValueError("replay labels do not all match engine results")
    if report["answered"] < 2 or report["escalated"] < 1:
        raise ValueError("replay did not exercise required answer and escalation paths")
    return report


def _source_commit(source: Path) -> str:
    result = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode or not SHA.fullmatch(result.stdout.strip()):
        raise ValueError("engine source is not a Git commit")
    return result.stdout.strip()


def build(pack_dir: Path, engine_source: Path) -> dict:
    pack_dir = Path(pack_dir)
    manifest = read_json(pack_dir / "manifest.json")
    knowledge = read_json(pack_dir / "knowledge.json")
    suite = read_json(pack_dir / "suite.json")
    if _source_commit(engine_source) != manifest.get("engine_source_commit"):
        raise ValueError("pack engine commit differs from supplied source checkout")
    report = validate_payload(manifest, knowledge, suite)
    payload = {"format": "a2z-resolution-pack-v1", "manifest": manifest,
               "knowledge": knowledge, "suite": suite, "replay_report": report}
    return {"payload": payload, "sha256": digest(payload)}


def write_bundle(bundle: dict, output: Path) -> dict:
    output = Path(output)
    if output.exists():
        raise ValueError("bundle output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(bundle) + b"\n"
    with output.open("xb") as file:
        file.write(data)
    return {"bundle": str(output), "sha256": bundle["sha256"],
            "id": bundle["payload"]["manifest"]["id"],
            "version": bundle["payload"]["manifest"]["version"]}


def verify_bundle(bundle: dict) -> dict:
    if set(bundle) != {"payload", "sha256"} or not isinstance(bundle["payload"], dict):
        raise ValueError("invalid bundle envelope")
    if digest(bundle["payload"]) != bundle["sha256"]:
        raise ValueError("bundle content hash mismatch")
    payload = bundle["payload"]
    if set(payload) != {"format", "manifest", "knowledge", "suite", "replay_report"} or payload["format"] != "a2z-resolution-pack-v1":
        raise ValueError("invalid pack format")
    report = validate_payload(payload["manifest"], payload["knowledge"], payload["suite"])
    if report != payload["replay_report"]:
        raise ValueError("replay report differs from local evaluation")
    return {"id": payload["manifest"]["id"], "version": payload["manifest"]["version"],
            "sha256": bundle["sha256"], "replay": report,
            "evidence_class": "SYNTHETIC_ONLY"}


def _private_registry(root: Path) -> Path:
    root = Path(root)
    created = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(root, 0o700)
    metadata = root.stat()
    if root.is_symlink() or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("registry must be a user-owned private directory, mode 0700")
    return root


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", prefix=".write-", dir=path.parent, delete=False) as file:
        temp = Path(file.name)
        os.chmod(temp, 0o600)
        file.write(canonical(value) + b"\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def install(bundle_path: Path, registry: Path) -> dict:
    bundle = read_json(Path(bundle_path))
    result = verify_bundle(bundle)
    root = _private_registry(registry)
    dest = root / "packs" / result["id"] / result["version"] / result["sha256"]
    version_dir = dest.parent
    if version_dir.exists() and any(item.name != result["sha256"] for item in version_dir.iterdir()):
        raise ValueError("pack id and version already refer to different content")
    if dest.exists():
        if dest.is_symlink():
            raise ValueError("installed pack directory cannot be a symlink")
        if read_json(dest / "bundle.json") != bundle:
            raise ValueError("installed bundle differs from requested content")
        _installed(root, result["id"], result["version"], result["sha256"])
    else:
        dest.mkdir(parents=True, mode=0o700)
        _atomic_json(dest / "bundle.json", bundle)
        _atomic_json(dest / "knowledge.json", bundle["payload"]["knowledge"])
        os.chmod(dest / "bundle.json", 0o400)
        os.chmod(dest / "knowledge.json", 0o400)
    return {**result, "installed_at": str(dest), "knowledge_path": str(dest / "knowledge.json")}


def _installed(registry: Path, pack_id: str, version: str, sha256: str) -> tuple[Path, dict]:
    if not SLUG.fullmatch(pack_id) or not VERSION.fullmatch(version) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("invalid installed pack reference")
    dest = _private_registry(registry) / "packs" / pack_id / version / sha256
    if dest.is_symlink():
        raise ValueError("installed pack directory cannot be a symlink")
    bundle = read_json(dest / "bundle.json")
    metadata = verify_bundle(bundle)
    if (metadata["id"], metadata["version"], metadata["sha256"]) != (pack_id, version, sha256):
        raise ValueError("installed pack identity mismatch")
    knowledge = read_json(dest / "knowledge.json")
    if knowledge != bundle["payload"]["knowledge"]:
        raise ValueError("installed knowledge differs from verified bundle")
    return dest, metadata


def activate(registry: Path, customer_key: str, pack_id: str, version: str, sha256: str) -> dict:
    if not SLUG.fullmatch(customer_key):
        raise ValueError("customer key must be a pseudonymous slug")
    dest, metadata = _installed(registry, pack_id, version, sha256)
    pointer = {"customer_key": customer_key, "id": pack_id, "version": version,
               "sha256": sha256, "activated_at": datetime.now(UTC).isoformat()}
    _atomic_json(_private_registry(registry) / "active" / f"{customer_key}.json", pointer)
    return {**metadata, "customer_key": customer_key, "knowledge_path": str(dest / "knowledge.json")}


def active(registry: Path, customer_key: str) -> dict:
    if not SLUG.fullmatch(customer_key):
        raise ValueError("customer key must be a pseudonymous slug")
    pointer = read_json(_private_registry(registry) / "active" / f"{customer_key}.json")
    if set(pointer) != {"customer_key", "id", "version", "sha256", "activated_at"} or pointer["customer_key"] != customer_key:
        raise ValueError("active pointer invalid")
    dest, metadata = _installed(registry, pointer["id"], pointer["version"], pointer["sha256"])
    return {**metadata, "customer_key": customer_key, "knowledge_path": str(dest / "knowledge.json"),
            "activated_at": pointer["activated_at"]}
