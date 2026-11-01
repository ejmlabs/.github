import copy
import sys
import unittest
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workflows
import pr_guidance as guidance
from governance import REQUIRED_CONTEXTS, GitHub

SHA = "a" * 40


def pull() -> dict[str, Any]:
    return {"head": {"sha": SHA, "repo": {"full_name": "ejmlabs/example"}},
            "base": {"ref": "main", "repo": {"full_name": "ejmlabs/example"}},
            "body": "Author text", "state": "open", "draft": False, "labels": []}


class GuidanceTests(unittest.TestCase):
    def test_guidance_tracks_current_gate_states(self) -> None:
        pr = pull()
        self.assertIn("admit this head", guidance.render(pr, {}))
        self.assertIn("mark it Ready", guidance.render({**pr, "draft": True}, {}))
        self.assertIn("retarget", guidance.render({**pr, "base": {**pr["base"], "ref": "other"}}, {}))
        self.assertIn("fork", guidance.render({**pr, "head": {**pr["head"], "repo": None}}, {}))
        self.assertIn("stop is pending", guidance.render({**pr, "labels": [{"name": "gate:revoke"}]}, {}))
        self.assertIn("failed checks", guidance.render(pr, {"Quality": {"state": "failure"}}))
        passed = {name: {"state": "success"} for name in REQUIRED_CONTEXTS}
        text = guidance.render(pr, passed)
        self.assertIn("gate:approve", text)
        self.assertIn("CodeQL", text)
        self.assertNotIn("/approve", text)
        self.assertIn(SHA, text)

    def test_body_preserves_author_text_and_rejects_broken_markers(self) -> None:
        section = guidance.render(pull(), {})
        body = guidance.update_body("Author text", section)
        self.assertTrue(body.endswith("Author text"))
        self.assertEqual(body, guidance.update_body(body, section))
        for broken in (guidance.START, guidance.END + guidance.START, body + guidance.START):
            with self.assertRaises(ValueError):
                guidance.update_body(broken, section)
        with self.assertRaises(ValueError):
            guidance.update_body("x" * 60000, section)

    def test_refresh_retries_concurrent_edits_and_is_idempotent(self) -> None:
        class API:
            def __init__(self) -> None:
                self.pr = pull()
                self.reads = 0
                self.writes = 0

            def request(self, path: str, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
                assert path == "/pulls/1"
                if method == "PATCH":
                    assert data is not None
                    self.pr["body"] = data["body"]
                    self.writes += 1
                else:
                    self.reads += 1
                    if self.reads == 2:
                        self.pr["head"]["sha"] = "b" * 40
                        self.pr["body"] += " edited"
                return copy.deepcopy(self.pr)

            def statuses(self, sha: str) -> dict[str, dict[str, Any]]:
                assert len(sha) == 40
                return {}

        api = API()
        guidance.refresh(cast("GitHub", api), 1)
        guidance.refresh(cast("GitHub", api), 1)
        self.assertEqual(api.writes, 1)
        self.assertIn("b" * 40, api.pr["body"])
        self.assertTrue(api.pr["body"].endswith("Author text edited"))

    def test_guidance_jobs_use_only_metadata_permissions(self) -> None:
        jobs = build_workflows.governance()["jobs"]
        for name in ("guidance", "guidance_finish"):
            job = jobs[name]
            self.assertEqual(job["permissions"], {"contents": "read", "pull-requests": "write", "statuses": "read"})
            self.assertIn("head.repo.full_name == github.repository", job["if"])
            self.assertEqual(len(job["steps"]), 1)
            self.assertNotIn("uses", job["steps"][0])
