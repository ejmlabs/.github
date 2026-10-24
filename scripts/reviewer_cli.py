"""Run the pinned CLI while recording only trusted completion metadata."""
import os
from pathlib import Path

from pr_agent import cli
from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler


def main():
    sidecar = Path(os.environ["RUNNER_TEMP"], "reviewer-finish-reasons.txt")
    # A prior attempt's evidence must never make a later attempt complete.
    sidecar.open("x", encoding="utf-8").close()
    completion = LiteLLMAIHandler._get_completion
    limit = int(os.environ["CONFIG__MAX_OUTPUT_TOKENS"])

    async def recorded_completion(self, *args, **kwargs):
        reason = "error"
        try:
            result = await completion(self, *args, **kwargs)
            # Never write arbitrary provider/model strings to the sidecar.
            reason = result[1] if result[1] in ("stop", "length", "content_filter") else "missing"
            usage = result[2].get("usage")
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

    LiteLLMAIHandler._get_completion = recorded_completion
    try:
        # This is the same entry point as python -m pr_agent.cli.
        return cli.run()
    finally:
        LiteLLMAIHandler._get_completion = completion


if __name__ == "__main__":
    raise SystemExit(main())
