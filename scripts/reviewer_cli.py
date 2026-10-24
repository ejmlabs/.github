"""Run the pinned CLI while recording only trusted completion metadata."""
import os
from pathlib import Path

from litellm.llms.xai.chat.transformation import XAIChatConfig
from pr_agent import cli
from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler


def main():
    sidecar = Path(os.environ["RUNNER_TEMP"], "reviewer-finish-reasons.txt")
    # A prior attempt's evidence must never make a later attempt complete.
    sidecar.open("x", encoding="utf-8").close()
    completion = LiteLLMAIHandler._get_completion
    transform = XAIChatConfig.transform_response
    limit = int(os.environ["CONFIG__MAX_OUTPUT_TOKENS"])

    def recorded_transform(self, model, raw_response, *args, **kwargs):
        raw_reason = raw_response.json()["choices"][0].get("finish_reason")
        response = transform(self, model, raw_response, *args, **kwargs)
        # LiteLLM 1.105.0 gives both raw stop and null/missing reasons normalized
        # stop with no native field. Preserve raw provenance using fixed tokens.
        response._hidden_params["reviewer_raw_finish_reason"] = (
            raw_reason if raw_reason in ("stop", "length", "content_filter") else "missing")
        return response

    async def recorded_completion(self, *args, **kwargs):
        reason = "error"
        try:
            result = await completion(self, *args, **kwargs)
            # Never write arbitrary provider/model strings to the sidecar.
            reason = result[1] if result[1] in ("stop", "length", "content_filter") else "missing"
            response = result[2]
            choice = response["choices"][0]
            native = choice.get("provider_specific_fields")
            if (choice.get("finish_reason") != reason
                    or response._hidden_params.get("reviewer_raw_finish_reason") != reason
                    or (native is not None and "native_finish_reason" in native
                        and native["native_finish_reason"] != reason)):
                reason = "missing"
            usage = response.get("usage")
            if usage is not None:
                tokens = usage.get("completion_tokens")
                if type(tokens) is not int or tokens < 0 or tokens >= limit:
                    reason = "token_limit"
            return result
        except BaseException:
            reason = "error"
            raise
        finally:
            with sidecar.open("a", encoding="utf-8") as output:
                output.write(reason + "\n")

    XAIChatConfig.transform_response = recorded_transform
    LiteLLMAIHandler._get_completion = recorded_completion
    try:
        # This is the same entry point as python -m pr_agent.cli.
        return cli.run()
    finally:
        LiteLLMAIHandler._get_completion = completion
        XAIChatConfig.transform_response = transform


if __name__ == "__main__":
    raise SystemExit(main())
