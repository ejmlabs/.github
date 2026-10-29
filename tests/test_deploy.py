import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deploy

PRODUCTION: dict[str, Any] = {"name": "ejmlabs-cli", "routes": [{"pattern": "cli.ejmlabs.com", "custom_domain": True}], "assets": {"directory": "./dist"}}
STAGING: dict[str, Any] = {"name": "ejmlabs-cli-staging", "routes": [{"pattern": "cli-staging.ejmlabs.com", "custom_domain": True}], "assets": {"directory": "./dist"}}


class DeployTests(unittest.TestCase):
    def test_site_config_reads_comments_and_trailing_commas(self) -> None:
        text = '{\n    // the site\n    "$schema": "https://unpkg.com/wrangler/config-schema.json",\n    "routes": [{ "pattern": "a.ejmlabs.com", },],\n}\n'
        self.assertEqual(deploy.site_config(text), {"$schema": "https://unpkg.com/wrangler/config-schema.json", "routes": [{"pattern": "a.ejmlabs.com"}]})
        with self.assertRaises(ValueError):
            deploy.site_config("[]")

    def test_production_deploys_the_top_level_config(self) -> None:
        self.assertEqual(deploy.check(PRODUCTION, "production"), [])

    def test_staging_needs_its_own_worker_and_routes(self) -> None:
        self.assertEqual(deploy.check({**PRODUCTION, "env": {"staging": STAGING}}, "staging"), ["--env", "staging"])
        for staging in (None, {**STAGING, "routes": []}, {**STAGING, "routes": PRODUCTION["routes"]}, {**STAGING, "name": PRODUCTION["name"]},
                        {key: value for key, value in STAGING.items() if key != "name"}):
            with self.subTest(staging=staging), self.assertRaisesRegex(ValueError, "Staging needs"):
                deploy.check({**PRODUCTION, "env": {} if staging is None else {"staging": staging}}, "staging")

    def test_no_build_command_runs_beside_the_token(self) -> None:
        for config in ({**PRODUCTION, "build": {"command": "npm run build"}}, {**PRODUCTION, "env": {"staging": {**STAGING, "build": {"command": "x"}}}}):
            for environment in deploy.ENVIRONMENTS:
                with self.subTest(config=config, environment=environment), self.assertRaisesRegex(ValueError, "build command"):
                    deploy.check(config, environment)
        with self.assertRaisesRegex(ValueError, "Unknown deploy environment"):
            deploy.check(PRODUCTION, "preview")

    def test_production_requires_a_human_reviewer_rule(self) -> None:
        self.assertEqual(deploy.required_reviewers({"protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "User"}]}]}), 1)
        for environment in ({}, {"protection_rules": None}, {"protection_rules": [{"type": "wait_timer", "wait_timer": 5}]},
                            {"protection_rules": [{"type": "required_reviewers", "reviewers": []}]}):
            with self.subTest(environment=environment):
                self.assertEqual(deploy.required_reviewers(environment), 0)

    def test_an_empty_token_stops_before_any_deploy_step(self) -> None:
        for environment in deploy.ENVIRONMENTS:
            with self.subTest(environment=environment), mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "", "PROFILE": "ejmlabs"}), \
                    mock.patch.object(sys, "argv", ["deploy.py", environment]), mock.patch.object(deploy, "require_approval") as approval, \
                    self.assertRaisesRegex(ValueError, "secrets: inherit"):
                deploy.main()
            approval.assert_not_called()

    def test_every_site_packs_its_config(self) -> None:
        for profile, (_, config, files) in deploy.SITES.items():
            with self.subTest(profile=profile):
                self.assertTrue(any(config == path or config.startswith(path + "/") for path in files))


if __name__ == "__main__":
    unittest.main()
