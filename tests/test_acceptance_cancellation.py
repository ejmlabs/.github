"""Bounded hosted hold for an unmerged human-gate acceptance fixture."""

import os
import time
import unittest


@unittest.skipUnless(
    os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("GITHUB_REPOSITORY") == "ejmlabs/.github",
    "Hosted cancellation fixture only",
)
class CancellationWindowTests(unittest.TestCase):
    def test_bounded_cancellation_window(self):
        print("EJM_ACCEPTANCE_CANCELLATION_ARMED: 180-second bound", flush=True)
        time.sleep(180)
