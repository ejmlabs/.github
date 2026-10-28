"""Optional offline proof against the pinned installed reviewer and library."""
import asyncio
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workflows


@unittest.skipUnless(importlib.util.find_spec("pr_agent"), "Pinned reviewer is not installed")
class ProviderSettingsProof(unittest.TestCase):
    def test_label_gate_uses_the_reviewers_own_negative_answer_rule(self) -> None:
        import governance
        from pr_agent.algo.utils import is_value_no  # type: ignore[import-not-found]  # optional reviewer packages are absent from the dev group
        for value in (None, "", "No", " no ", "NONE", "false", "False.", "No.", "Yes", "n/a", 0, 1, True, False, [], ["No"]):
            with self.subTest(value=value):
                self.assertEqual(governance.is_value_no(value), is_value_no(value))

    def test_provider_reasoning_and_no_fallback(self) -> None:
        self.assertEqual(version("pr-agent"), "0.48.0")
        self.assertEqual(version("litellm"), "1.105.0")
        review = next(step for step in build_workflows.governance()["jobs"]["ai"]["steps"]
                      if step.get("name") == "Automated review")
        with tempfile.TemporaryDirectory() as directory:
            dummy_key = "".join(chr(value) for value in (111, 102, 102, 108, 105, 110, 101, 45, 107, 101, 121))
            env = {**review["env"], "XAI__KEY": dummy_key, "HOME": directory, "LITELLM_LOCAL_MODEL_COST_MAP": "True"}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch("socket.socket.connect", side_effect=AssertionError("Network is forbidden")), \
                    mock.patch("socket.create_connection", side_effect=AssertionError("Network is forbidden")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                import litellm  # type: ignore[import-not-found]  # optional reviewer packages are absent from the dev group
                from pr_agent.algo.ai_handlers import litellm_ai_handler  # type: ignore[import-not-found]  # optional reviewer packages are absent from the dev group
                from pr_agent.algo.pr_processing import retry_with_fallback_models  # type: ignore[import-not-found]  # optional reviewer packages are absent from the dev group
                from pr_agent.config_loader import get_settings  # type: ignore[import-not-found]  # optional reviewer packages are absent from the dev group

                get_settings().reload()
                response = litellm.ModelResponse(choices=[{"message": {"content": "Offline response"}, "finish_reason": "stop"}])
                with mock.patch.object(litellm_ai_handler, "acompletion", new_callable=mock.AsyncMock, return_value=response) as completion:
                    handler = litellm_ai_handler.LiteLLMAIHandler()
                    self.assertEqual(get_settings().config.fallback_models, [])
                    result = asyncio.run(retry_with_fallback_models(
                        lambda model: handler.chat_completion(model, "Synthetic system", "Synthetic change")))
                    self.assertEqual(result, ("Offline response", "stop"))
                    assert completion.await_args is not None
                    self.assertEqual(completion.await_args.kwargs["model"], "xai/grok-4.5")
                    self.assertEqual(completion.await_args.kwargs["reasoning_effort"], "high")
                    self.assertTrue(completion.await_args.kwargs.get("api_key") == dummy_key)

                    completion.reset_mock()
                    completion.side_effect = TimeoutError("Synthetic failure")
                    attempted: list[str] = []

                    async def fail(model: str) -> Any:
                        attempted.append(model)
                        return await handler.chat_completion(model, "Synthetic system", "Synthetic change")

                    with self.assertRaisesRegex(Exception, "Failed to generate prediction"):
                        asyncio.run(retry_with_fallback_models(fail))
                    self.assertEqual(attempted, ["xai/grok-4.5"])
                    self.assertGreaterEqual(completion.await_count, 1)
                    self.assertEqual({call.kwargs["model"] for call in completion.await_args_list}, {"xai/grok-4.5"})


if __name__ == "__main__":
    unittest.main()
