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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workflows


@unittest.skipUnless(importlib.util.find_spec("pr_agent"), "Pinned reviewer is not installed")
class ProviderSettingsProof(unittest.TestCase):
    def test_provider_reasoning_no_fallback_and_message_logging(self):
        self.assertEqual(version("pr-agent"), "0.48.0")
        self.assertEqual(version("litellm"), "1.105.0")
        review = next(step for step in build_workflows.governance()["jobs"]["ai"]["steps"]
                      if step.get("name") == "Independent automated review")
        self.assertEqual(review["env"]["LITELLM_MODE"], "PRODUCTION")
        with tempfile.TemporaryDirectory() as directory:
            dummy_key = "".join(chr(value) for value in (111, 102, 102, 108, 105, 110, 101, 45, 107, 101, 121))
            env = {**review["env"], "XAI__KEY": dummy_key, "HOME": directory}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch("socket.socket.connect", side_effect=AssertionError("Network is forbidden")), \
                    mock.patch("socket.create_connection", side_effect=AssertionError("Network is forbidden")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                import litellm
                from pr_agent.config_loader import get_settings
                from pr_agent.algo.ai_handlers import litellm_ai_handler
                from pr_agent.algo.pr_processing import retry_with_fallback_models

                get_settings().reload()
                response = litellm.ModelResponse(choices=[{"message": {"content": "Offline response"}, "finish_reason": "stop"}])
                with mock.patch.object(litellm_ai_handler, "acompletion", new_callable=mock.AsyncMock, return_value=response) as completion:
                    handler = litellm_ai_handler.LiteLLMAIHandler()
                    self.assertIs(litellm.turn_off_message_logging, True)
                    self.assertEqual(get_settings().config.fallback_models, [])
                    result = asyncio.run(retry_with_fallback_models(
                        lambda model: handler.chat_completion(model, "Synthetic system", "Synthetic change")))
                    self.assertEqual(result, ("Offline response", "stop"))
                    self.assertEqual(completion.await_args.kwargs["model"], "xai/grok-4.5")
                    self.assertEqual(completion.await_args.kwargs["reasoning_effort"], "high")
                    self.assertTrue(completion.await_args.kwargs.get("api_key") == dummy_key)

                    completion.reset_mock()
                    completion.side_effect = asyncio.TimeoutError("Synthetic failure")
                    attempted = []

                    async def fail(model):
                        attempted.append(model)
                        return await handler.chat_completion(model, "Synthetic system", "Synthetic change")

                    with self.assertRaises(Exception):
                        asyncio.run(retry_with_fallback_models(fail))
                    self.assertEqual(attempted, ["xai/grok-4.5"])
                    self.assertGreaterEqual(completion.await_count, 1)
                    self.assertEqual({call.kwargs["model"] for call in completion.await_args_list}, {"xai/grok-4.5"})


if __name__ == "__main__":
    unittest.main()
