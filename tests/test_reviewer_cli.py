import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_workflows import source


class ReviewerTerminationTests(unittest.TestCase):
    def exercise(self, responses, raw_reasons=None, transform_response=True):
        class Response(dict):
            def __init__(self, value):
                super().__init__(value)
                self._hidden_params = {}

        class Config:
            def transform_response(self, model, raw_response):
                return raw_response.response

        transform = Config.transform_response
        pending = iter(enumerate(responses))

        async def complete(*args, **kwargs):
            index, result = next(pending)
            if isinstance(result, BaseException):
                raise result
            content, reason, metadata = result
            response = Response(metadata)
            response.setdefault("choices", [{"finish_reason": reason}])
            if transform_response:
                raw_reason = reason if raw_reasons is None else raw_reasons[index]
                raw = mock.Mock(response=response)
                raw.json.return_value = {"choices": [{"finish_reason": raw_reason}]}
                Config().transform_response("synthetic", raw)
            return content, reason, response

        class Handler:
            _get_completion = mock.AsyncMock(side_effect=complete)

        original = Handler._get_completion

        def run():
            async def calls():
                for _ in responses:
                    try:
                        await Handler()._get_completion(model="synthetic")
                    except Exception:
                        pass
            asyncio.run(calls())
            return 0

        modules = {"pr_agent": types.ModuleType("pr_agent"), "pr_agent.cli": types.ModuleType("pr_agent.cli"),
                   "pr_agent.algo": types.ModuleType("pr_agent.algo"),
                   "pr_agent.algo.ai_handlers": types.ModuleType("pr_agent.algo.ai_handlers"),
                   "pr_agent.algo.ai_handlers.litellm_ai_handler": types.ModuleType("pr_agent.algo.ai_handlers.litellm_ai_handler")}
        modules["litellm.llms.xai.chat.transformation"] = types.ModuleType("litellm.llms.xai.chat.transformation")
        modules["litellm.llms.xai.chat.transformation"].XAIChatConfig = Config
        modules["pr_agent"].cli = modules["pr_agent.cli"]
        modules["pr_agent.cli"].run = run
        modules["pr_agent.algo.ai_handlers.litellm_ai_handler"].LiteLLMAIHandler = Handler
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules, modules), \
                mock.patch.dict(os.environ, {"RUNNER_TEMP": directory, "CONFIG__MAX_OUTPUT_TOKENS": "16000"}):
            namespace = {}
            exec(compile(source("reviewer_cli.py", True), "trusted-wrapper", "exec"), namespace)
            self.assertEqual(namespace["main"](), 0)
            self.assertIs(Handler._get_completion, original)
            self.assertIs(Config.transform_response, transform)
            return Path(directory, "reviewer-finish-reasons.txt").read_text().splitlines()

    def test_records_each_reason_without_model_text(self):
        reasons = ("stop", "length", "content_filter", None, "MODEL-TEXT-MARKER")
        output = self.exercise([("MODEL-TEXT-MARKER", reason, {}) for reason in reasons])
        self.assertEqual(output, ["stop", "length", "content_filter", "missing", "missing"])

    def test_normalized_stop_requires_raw_stop(self):
        reasons = ("stop", None, "", "error", "unknown", "length")
        self.assertEqual(self.exercise([("text", "stop", {}) for _ in reasons], raw_reasons=reasons),
                         ["stop", "missing", "missing", "missing", "missing", "missing"])
        self.assertEqual(self.exercise([("text", "stop", {})], transform_response=False), ["missing"])

    def test_exposed_native_reason_must_agree(self):
        reasons = ("stop", None, "", "error", "unknown", "length")
        responses = [("text", "stop", {"choices": [{"finish_reason": "stop", "provider_specific_fields": {
            "native_finish_reason": reason}}]}) for reason in reasons]
        self.assertEqual(self.exercise(responses), ["stop", "missing", "missing", "missing", "missing", "missing"])

    def test_failed_attempt_cannot_be_hidden_by_a_successful_retry(self):
        self.assertEqual(self.exercise([RuntimeError("MODEL-TEXT-MARKER"), ("text", "stop", {})]), ["error", "stop"])
        self.assertEqual(self.exercise([("text", "stop", {"usage": "MODEL-TEXT-MARKER"}),
                                        ("text", "stop", {})]), ["error", "stop"])

    def test_per_call_token_limit_is_recorded(self):
        responses = [("text", "stop", {"usage": {"completion_tokens": tokens}}) for tokens in (15999, 16000, 16001)]
        self.assertEqual(self.exercise(responses), ["stop", "token_limit", "token_limit"])
