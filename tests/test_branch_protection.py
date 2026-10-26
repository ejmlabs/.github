import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import branch_protection as protection

URL = "https://api.github.com/repos/ejmlabs/ejm-ui/branches/main/protection"
SAVED = {
    "url": URL,
    "required_status_checks": {
        "url": URL + "/required_status_checks", "strict": True, "enforcement_level": "everyone",
        "contexts_url": URL + "/required_status_checks/contexts",
        "contexts": ["Quality", "Automated review", "Legacy"],
        "checks": [{"context": "Quality", "app_id": 15368}, {"context": "Automated review", "app_id": 15368},
                   {"context": "Legacy", "app_id": None}],
    },
    "enforce_admins": {"url": URL + "/enforce_admins", "enabled": True},
    "required_pull_request_reviews": {
        "url": URL + "/required_pull_request_reviews",
        "dismissal_restrictions": {"url": "x", "users_url": "x", "teams_url": "x",
                                   "users": [{"login": "b"}, {"login": "a"}], "teams": [{"slug": "security"}], "apps": []},
        "dismiss_stale_reviews": True, "require_code_owner_reviews": True,
        "required_approving_review_count": 1, "require_last_push_approval": True,
    },
    "restrictions": {"url": "x", "users_url": "x", "teams_url": "x", "apps_url": "x",
                     "users": [], "teams": [], "apps": [{"slug": "governance", "id": 1}]},
    "required_signatures": {"url": URL + "/required_signatures", "enabled": False},
    "required_linear_history": {"enabled": True},
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
    "block_creations": {"enabled": False},
    "required_conversation_resolution": {"enabled": True},
    "lock_branch": {"enabled": False},
    "allow_fork_syncing": {"enabled": False},
}


class ReadToWriteTests(unittest.TestCase):
    def test_full_replace_body_uses_the_write_shape(self):
        body = protection.put_body(SAVED)
        self.assertIs(body["enforce_admins"], True)
        self.assertIs(body["required_linear_history"], True)
        self.assertIs(body["lock_branch"], False)
        self.assertEqual(body["required_pull_request_reviews"]["dismissal_restrictions"],
                         {"users": ["a", "b"], "teams": ["security"], "apps": []})
        self.assertEqual(body["restrictions"], {"users": [], "teams": [], "apps": ["governance"]})
        self.assertNotIn("url", body)
        self.assertNotIn("required_signatures", body)
        self.assertNotIn("contexts", body["required_status_checks"])

    def test_app_binding_is_kept_and_unbound_checks_stay_explicitly_unbound(self):
        self.assertEqual(protection.checks(SAVED), [
            {"context": "Automated review", "app_id": 15368}, {"context": "Legacy", "app_id": -1},
            {"context": "Quality", "app_id": 15368}])

    def test_contexts_only_read_is_refused(self):
        saved = copy.deepcopy(SAVED)
        del saved["required_status_checks"]["checks"]
        with self.assertRaisesRegex(ValueError, "contexts-only"):
            protection.put_body(saved)

    def test_lock_is_a_full_replace_with_only_the_lock_changed(self):
        locked = protection.put_body(SAVED, lock=True)
        unlocked = protection.put_body(SAVED)
        self.assertIs(locked.pop("lock_branch"), True)
        unlocked.pop("lock_branch")
        self.assertEqual(locked, unlocked)

    def test_unknown_fields_fail_closed(self):
        saved = dict(SAVED, new_setting={"enabled": True})
        with self.assertRaisesRegex(ValueError, "unhandled"):
            protection.put_body(saved)

    def test_nested_unknown_fields_fail_closed(self):
        cases = {
            "required_pull_request_reviews": lambda p: p["required_pull_request_reviews"].update(new_rule=True),
            "required_status_checks": lambda p: p["required_status_checks"].update(new_rule=True),
            "required_status_checks.checks": lambda p: p["required_status_checks"]["checks"][0].update(new_rule=1),
            "restrictions": lambda p: p["restrictions"].update(new_rule=[]),
            "required_pull_request_reviews.dismissal_restrictions":
                lambda p: p["required_pull_request_reviews"]["dismissal_restrictions"].update(new_rule=[]),
            "enforce_admins": lambda p: p["enforce_admins"].update(new_rule=True),
        }
        for where, change in cases.items():
            with self.subTest(where=where):
                saved = copy.deepcopy(SAVED)
                change(saved)
                with self.assertRaisesRegex(ValueError, "unhandled protection fields at " + where + ":"):
                    protection.put_body(saved)
                with self.assertRaisesRegex(ValueError, "unhandled"):
                    protection.differences(SAVED, saved)

    def test_bypass_allowances_are_written_and_compared(self):
        saved = copy.deepcopy(SAVED)
        saved["required_pull_request_reviews"]["bypass_pull_request_allowances"] = {
            "users": [{"login": "owner"}], "teams": [], "apps": [{"slug": "governance", "id": 1}]}
        body = protection.put_body(saved)
        self.assertEqual(body["required_pull_request_reviews"]["bypass_pull_request_allowances"],
                         {"users": ["owner"], "teams": [], "apps": ["governance"]})
        current = copy.deepcopy(saved)
        current["required_pull_request_reviews"]["bypass_pull_request_allowances"]["users"].append({"login": "x"})
        self.assertEqual(protection.differences(saved, current),
                         ["required_pull_request_reviews.bypass_pull_request_allowances.users"])
        self.assertEqual(protection.differences(saved, SAVED),
                         ["required_pull_request_reviews.bypass_pull_request_allowances"])

    def test_lift_drops_exactly_one_context(self):
        body = protection.status_checks_body(SAVED, without="Automated review")
        self.assertEqual([entry["context"] for entry in body["checks"]], ["Legacy", "Quality"])
        with self.assertRaisesRegex(ValueError, "not in the saved"):
            protection.status_checks_body(SAVED, without="Missing")


class ReadBackTests(unittest.TestCase):
    def test_round_trip_read_back_is_clean(self):
        self.assertEqual(protection.differences(SAVED, copy.deepcopy(SAVED)), [])

    def test_lost_app_binding_is_found(self):
        current = copy.deepcopy(SAVED)
        current["required_status_checks"]["checks"][1]["app_id"] = None
        self.assertEqual(protection.differences(SAVED, current), ["required_status_checks.checks"])

    def test_each_dropped_setting_is_found_field_by_field(self):
        cases = {
            "enforce_admins": lambda p: p["enforce_admins"].update(enabled=False),
            "required_signatures": lambda p: p["required_signatures"].update(enabled=True),
            "required_pull_request_reviews.require_last_push_approval":
                lambda p: p["required_pull_request_reviews"].update(require_last_push_approval=False),
            "restrictions.apps": lambda p: p["restrictions"].update(apps=[]),
            "allow_force_pushes": lambda p: p["allow_force_pushes"].update(enabled=True),
        }
        for path, change in cases.items():
            with self.subTest(path=path):
                current = copy.deepcopy(SAVED)
                change(current)
                self.assertEqual(protection.differences(SAVED, current), [path])

    def test_lift_read_back_allows_only_the_lifted_context(self):
        expected = protection.expected_after_lift(SAVED, "Automated review")
        self.assertEqual(protection.differences(SAVED, expected), ["required_status_checks.checks"])
        self.assertEqual(protection.differences(expected, copy.deepcopy(expected)), [])
        with self.assertRaisesRegex(ValueError, "not in the saved"):
            protection.expected_after_lift(SAVED, "Missing")

    def test_lift_read_back_finds_any_other_change(self):
        expected = protection.expected_after_lift(SAVED, "Automated review")
        cases = {
            "required_status_checks.strict": lambda p: p["required_status_checks"].update(strict=False),
            "required_status_checks.checks": lambda p: p["required_status_checks"]["checks"][0].update(app_id=None),
            "required_status_checks.enforcement_level":
                lambda p: p["required_status_checks"].update(enforcement_level="non_admins"),
            "lock_branch": lambda p: p["lock_branch"].update(enabled=True),
        }
        for path, change in cases.items():
            with self.subTest(path=path):
                current = copy.deepcopy(expected)
                change(current)
                self.assertEqual(protection.differences(expected, current), [path])

    def test_signature_difference_names_the_separate_call(self):
        self.assertIsNone(protection.signature_repair(SAVED, copy.deepcopy(SAVED)))
        current = copy.deepcopy(SAVED)
        current["required_signatures"]["enabled"] = True
        self.assertEqual(protection.signature_repair(SAVED, current), ("DELETE", "required_signatures"))
        self.assertEqual(protection.signature_repair(current, SAVED), ("POST", "required_signatures"))

if __name__ == "__main__":
    unittest.main()
