import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from resolution_network.core import (active, activate, build, canonical, digest, install,
                                     read_json, validate_payload, verify_bundle, write_bundle)
from resolution_engine.engine import resolve


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("A2Z_ENGINE_SOURCE", ROOT.parent / "a2z-resolution-engine"))
EXAMPLE = ROOT / "examples/guide-pack"


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_build_install_activate_liveops_knowledge_path(self):
        bundle = build(EXAMPLE, SOURCE)
        self.assertEqual(bundle["payload"]["replay_report"]["correct_against_declared_labels"], 4)
        output = self.root / "guide.a2zpack"
        write_bundle(bundle, output)
        installed = install(output, self.root / "private-registry")
        self.assertEqual(installed["evidence_class"], "SYNTHETIC_ONLY")
        self.assertEqual(install(output, self.root / "private-registry")["sha256"], bundle["sha256"])
        chosen = activate(self.root / "private-registry", "synthetic-customer", installed["id"],
                          installed["version"], installed["sha256"])
        selected = active(self.root / "private-registry", "synthetic-customer")
        self.assertEqual(chosen["knowledge_path"], selected["knowledge_path"])
        self.assertEqual(read_json(Path(selected["knowledge_path"])), bundle["payload"]["knowledge"])
        answer = resolve(read_json(Path(selected["knowledge_path"])),
                         {"id": "pilot-synthetic-1", "locale": "ar", "text": "فين دليل استخدام المنتج"})
        self.assertEqual(answer["article_id"], "ar-product-guide")

    def test_tampered_bundle_fails(self):
        bundle = build(EXAMPLE, SOURCE)
        bundle["payload"]["knowledge"]["articles"][0]["answer"] = "Changed"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_bundle(bundle)

    def test_bad_replay_and_missing_locale_fail(self):
        manifest = read_json(EXAMPLE / "manifest.json")
        knowledge = read_json(EXAMPLE / "knowledge.json")
        suite = read_json(EXAMPLE / "suite.json")
        suite["cases"][0]["expected_article_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "labels"):
            validate_payload(manifest, knowledge, suite)
        suite = read_json(EXAMPLE / "suite.json")
        suite["cases"] = [case for case in suite["cases"] if case["ticket"]["locale"] == "en"]
        with self.assertRaisesRegex(ValueError, "English and Arabic"):
            validate_payload(manifest, knowledge, suite)

    def test_version_cannot_change_content(self):
        bundle = build(EXAMPLE, SOURCE)
        first = self.root / "one.a2zpack"
        write_bundle(bundle, first)
        install(first, self.root / "registry")
        modified = copy.deepcopy(bundle)
        modified["payload"]["manifest"]["title"] = "Changed title"
        modified["sha256"] = digest(modified["payload"])
        second = self.root / "two.a2zpack"
        write_bundle(modified, second)
        with self.assertRaisesRegex(ValueError, "different content"):
            install(second, self.root / "registry")

    def test_installed_knowledge_tamper_fails_active(self):
        bundle = build(EXAMPLE, SOURCE)
        output = self.root / "guide.a2zpack"
        write_bundle(bundle, output)
        installed = install(output, self.root / "registry")
        activate(self.root / "registry", "synthetic-customer", installed["id"], installed["version"], installed["sha256"])
        knowledge_path = Path(installed["knowledge_path"])
        knowledge_path.chmod(0o600)
        knowledge_path.write_text(json.dumps({"fake": True}))
        with self.assertRaisesRegex(ValueError, "differs"):
            active(self.root / "registry", "synthetic-customer")


if __name__ == "__main__":
    unittest.main()
