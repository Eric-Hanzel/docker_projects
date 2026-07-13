import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ValidateFinalOutputsTests(unittest.TestCase):
    def test_missing_project_fails_cleanly(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / ".codex" / "scripts" / "validate_final_outputs.py"),
                "__missing_project__",
                "--root",
                str(ROOT),
                "--terminal-status",
                "COMPLETED_SUCCESS",
                "--require-audit",
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("missing deliverable dir" in item for item in payload["errors"]))

    def test_minimal_portable_success_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = "demo"
            deliverable = root / "Deliverable" / f"{project}-final"
            logs = root / "DP_LOGS" / f"{project}-final"
            (deliverable / "scripts").mkdir(parents=True)
            (deliverable / "initdb").mkdir()
            logs.mkdir(parents=True)

            for rel in [
                "README_QUICKSTART.md",
                "docker-compose.yml",
                "scripts/deploy.sh",
                "scripts/verify.sh",
                "scripts/reset.sh",
                "source-initialized.tar.gz",
                "initdb/README_NO_DB.md",
            ]:
                path = deliverable / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")

            for rel in ["preflight.md", "deploy.log", "summary.md"]:
                (logs / rel).write_text("ok\n", encoding="utf-8")
            (logs / "preflight.json").write_text("{}\n", encoding="utf-8")
            (logs / "verification_result.json").write_text(
                json.dumps({"passed": True, "basic_function_verified": True}),
                encoding="utf-8",
            )
            (logs / "audit_result.json").write_text(
                json.dumps(
                    {
                        "project_name": project,
                        "delivery_mode": "portable-deliverable",
                        "attempt": 1,
                        "verdict": "PASS",
                        "verified_url": "http://127.0.0.1:18080",
                        "basic_function_verified": True,
                        "blocking_findings": [],
                        "warnings": [],
                        "checked_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".codex" / "scripts" / "validate_final_outputs.py"),
                    project,
                    "--root",
                    str(root),
                    "--terminal-status",
                    "COMPLETED_SUCCESS",
                    "--require-audit",
                    "--json",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["ok"])


class RenderStateStatusTests(unittest.TestCase):
    def test_render_state_status_updates_status_file(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / ".codex" / "scripts" / "render_state_status.py")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = ROOT / ".codex" / "state" / "STATUS.md"
        self.assertTrue(status.exists())
        self.assertIn("APDv1 State Status", status.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
