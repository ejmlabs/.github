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
    def test_raw_xai_termination_survives_the_real_transform_and_handler(self):
        self.assertEqual(version("litellm"), "1.105.0")
        review = next(step for step in build_workflows.governance()["jobs"]["ai"]["steps"]
                      if step.get("name") == "Independent automated review")
        with tempfile.TemporaryDirectory() as directory:
            env = {**review["env"], "HOME": directory, "RUNNER_TEMP": directory,
                   "LITELLM_LOCAL_MODEL_COST_MAP": "True"}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch("socket.socket.connect", side_effect=AssertionError("Network is forbidden")), \
                    mock.patch("socket.create_connection", side_effect=AssertionError("Network is forbidden")), \
                    mock.patch("socket.getaddrinfo", side_effect=AssertionError("Network is forbidden")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                import httpx
                import litellm
                import reviewer_cli
                from litellm.llms.xai.chat.transformation import XAIChatConfig
                from pr_agent.config_loader import get_settings
                from pr_agent.algo.ai_handlers import litellm_ai_handler

                get_settings().reload()
                absent = object()
                reasons = ("stop", None, absent, "", "error", "network_error", "unknown", "length", "content_filter")
                pending = iter(reasons)
                observed = []

                async def completion(**kwargs):
                    reason = next(pending)
                    choice = {"index": 0, "message": {"role": "assistant", "content": "Synthetic review"}}
                    if reason is not absent:
                        choice["finish_reason"] = reason
                    body = {"id": "offline", "model": "grok-4.5", "created": 1, "object": "chat.completion",
                            "choices": [choice], "usage": {"completion_tokens": 1, "prompt_tokens": 1, "total_tokens": 2}}
                    raw = httpx.Response(200, json=body, request=httpx.Request("POST", "https://example.invalid/offline"))
                    response = XAIChatConfig().transform_response(
                        model="grok-4.5", raw_response=raw, model_response=litellm.ModelResponse(),
                        logging_obj=mock.Mock(), request_data={}, messages=[], optional_params={},
                        litellm_params={}, encoding=mock.Mock())
                    observed.append((response.choices[0].finish_reason, response.choices[0].provider_specific_fields))
                    return response

                def run():
                    async def calls():
                        handler = litellm_ai_handler.LiteLLMAIHandler()
                        for _ in reasons:
                            await handler._get_completion(model="xai/grok-4.5", messages=[])
                    asyncio.run(calls())
                    return 0

                original_transform = XAIChatConfig.transform_response
                original_completion = litellm_ai_handler.LiteLLMAIHandler._get_completion
                with mock.patch.object(litellm_ai_handler, "acompletion", side_effect=completion), \
                        mock.patch.object(reviewer_cli.cli, "run", side_effect=run):
                    self.assertEqual(reviewer_cli.main(), 0)
                self.assertIs(XAIChatConfig.transform_response, original_transform)
                self.assertIs(litellm_ai_handler.LiteLLMAIHandler._get_completion, original_completion)
                # Normal stop, null and absent are indistinguishable after the pinned
                # transform; only the raw-response marker makes the latter two fail.
                self.assertEqual(observed[:3], [("stop", {})] * 3)
                self.assertEqual(Path(directory, "reviewer-finish-reasons.txt").read_text().splitlines(),
                                 ["stop", "missing", "missing", "missing", "missing", "missing", "missing",
                                  "length", "content_filter"])

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
