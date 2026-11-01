import contextlib
import io
import json
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import configure_repositories as settings
import set_deploy_token as tool
from standards import SITE_DEPLOY

from deploy import ACCOUNT_ID

TOKEN = "fake-cloudflare-token-0123456789"


class Recorder:
    """Stands in for gh: records every call and fails the environments listed in fail."""

    def __init__(self, fail: frozenset[tuple[str, str]] = frozenset()) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.fail = fail

    def run(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, kwargs.get("input")))
        target = (args[args.index("--repo") + 1].split("/", 1)[1], args[args.index("--env") + 1])
        return subprocess.CompletedProcess(args, 1 if target in self.fail else 0, "", "HTTP 404" if target in self.fail else "")


def find(path: str) -> dict[str, Any] | None:
    if path.endswith("/secrets/" + tool.SECRET):
        return {"name": tool.SECRET, "updated_at": "2026-10-31T18:30:00Z"}
    return {"full_name": path}


class SetDeployTokenTests(unittest.TestCase):
    def run_main(self, argv: list[str], gh: Recorder, *, accepted: bool = True, finder: Any = find, reviewers: int = 1) -> tuple[str, MagicMock]:
        out = io.StringIO()
        configure = MagicMock(return_value={"required_reviewers": reviewers})
        with patch.object(subprocess, "run", gh.run), patch.object(settings, "find", finder), \
                patch.object(settings, "configure_environment", configure), patch.object(tool, "read_token", return_value=TOKEN), \
                patch.object(tool, "cloudflare_accepts", return_value=accepted), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            tool.main(argv)
        return out.getvalue(), configure

    def test_sets_both_environments_of_every_site_repository_through_stdin(self) -> None:
        gh = Recorder()
        output, configure = self.run_main([], gh)
        targets = {(args[args.index("--repo") + 1], args[args.index("--env") + 1]) for args, _ in gh.calls}
        self.assertEqual(targets, {(f"ejmlabs/{name}", env) for name in SITE_DEPLOY for env in ("staging", "production")})
        self.assertEqual(configure.call_count, len(SITE_DEPLOY) * 2)
        for args, stdin in gh.calls:
            self.assertEqual(stdin, TOKEN)
            self.assertNotIn(TOKEN, " ".join(args))
            self.assertEqual(args[:4], ["gh", "secret", "set", "CLOUDFLARE_API_TOKEN"])
        self.assertNotIn(TOKEN, output)
        self.assertIn(f"done: CLOUDFLARE_API_TOKEN is set in {len(SITE_DEPLOY) * 2} environments", output)

    def test_production_without_a_reviewer_still_gets_the_token_and_a_warning(self) -> None:
        output, _ = self.run_main(["--repository", "ejm-ui"], Recorder(), reviewers=0)
        self.assertEqual([line for line in output.splitlines() if line.startswith("warning:")], [f"warning: ejm-ui: {settings.NO_RELEASER}"])
        self.assertIn("ok   ejm-ui production", output)
        output, _ = self.run_main(["--repository", "ejm-ui"], Recorder())
        self.assertNotIn("warning:", output)

    def test_a_token_cloudflare_rejects_writes_nothing(self) -> None:
        gh = Recorder()
        with self.assertRaises(SystemExit) as stop:
            self.run_main([], gh, accepted=False)
        self.assertIn("nothing was written", str(stop.exception))
        self.assertEqual(gh.calls, [])

    def test_a_missing_repository_stops_before_the_prompt_and_any_write(self) -> None:
        gh = Recorder()
        with patch.object(tool, "read_token") as prompt, self.assertRaises(SystemExit) as stop:
            out = io.StringIO()
            with patch.object(subprocess, "run", gh.run), contextlib.redirect_stdout(out), \
                    patch.object(settings, "find", lambda path: None if path == "repos/ejmlabs/ejm-ide" else find(path)):
                tool.main([])
        self.assertIn("ejm-ide", str(stop.exception))
        prompt.assert_not_called()
        self.assertEqual(gh.calls, [])

    def test_one_failed_environment_does_not_stop_the_others_and_exits_nonzero(self) -> None:
        gh = Recorder(fail=frozenset({("ejm-ui", "production")}))
        with self.assertRaises(SystemExit) as stop:
            self.run_main([], gh)
        self.assertIn("1 environment", str(stop.exception))
        self.assertEqual(len(gh.calls), len(SITE_DEPLOY) * 2)

    def test_repository_option_limits_the_targets_and_dry_run_asks_nothing(self) -> None:
        gh = Recorder()
        self.run_main(["--repository", "ejm-ui"], gh)
        self.assertEqual({args[args.index("--repo") + 1] for args, _ in gh.calls}, {"ejmlabs/ejm-ui"})
        with patch.object(tool, "read_token") as prompt, contextlib.redirect_stdout(io.StringIO()) as out:
            tool.main(["--dry-run"])
        prompt.assert_not_called()
        self.assertEqual(out.getvalue().count("target ejmlabs/"), len(SITE_DEPLOY))

    def test_read_token_takes_one_piped_line_and_rejects_spaces(self) -> None:
        with patch.object(sys, "stdin", io.StringIO(TOKEN + "\nignored\n")):
            self.assertEqual(tool.read_token(), TOKEN)
        for bad in ("\n", "two words\n", "tab\there\n"):
            with patch.object(sys, "stdin", io.StringIO(bad)), self.assertRaises(ValueError):
                tool.read_token()

    def test_cloudflare_accepts_an_active_token_at_either_endpoint(self) -> None:
        seen: list[tuple[str, str | None]] = []

        def respond(active_on: str | None) -> Any:
            def urlopen(request: Any, timeout: float) -> Any:
                self.assertEqual(timeout, 30)
                seen.append((request.full_url, request.get_header("Authorization")))
                if active_on is None or not request.full_url.endswith(active_on):
                    raise urllib.error.URLError("refused")
                return io.BytesIO(json.dumps({"success": True, "result": {"status": "active"}}).encode())
            return urlopen

        with patch.object(urllib.request, "urlopen", respond(f"/accounts/{ACCOUNT_ID}/tokens/verify")):
            self.assertTrue(tool.cloudflare_accepts(TOKEN))
        self.assertEqual([url for url, _ in seen], [tool.CLOUDFLARE + path for path in tool.VERIFY_PATHS])
        self.assertTrue(all(url.startswith("https://api.cloudflare.com/") and auth == f"Bearer {TOKEN}" for url, auth in seen))
        with patch.object(urllib.request, "urlopen", respond(None)):
            self.assertFalse(tool.cloudflare_accepts(TOKEN))


if __name__ == "__main__":
    unittest.main()
