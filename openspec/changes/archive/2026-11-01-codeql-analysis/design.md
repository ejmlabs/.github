## Decisions

The caller runs only against main, so autobuild does not execute pull request code with a write-capable token. It grants the same permissions as the analysis job. The workflow accepts a comma-separated language string, allowing CodeQL to analyze Python and Actions sequentially.

The standards exception matches the entire generated caller and applies only to the shared standards repository. The reusable workflow retains the generated scaffold and pinned action checks. The repository settings tool permits the CodeQL action only in this repository until consumer rollout is designed.

## Rollout

The currently pinned standards must first admit these files, and advanced setup requires default code scanning setup to be disabled. Consumers need their own reviewed callers, action policy and pin changes.
