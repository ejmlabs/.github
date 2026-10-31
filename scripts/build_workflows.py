#!/usr/bin/env python3
"""Embed trusted scripts in reusable workflows so private callers need no read token."""
import base64
import json
import sys
from pathlib import Path
from typing import Any

from deploy import SITES

ROOT = Path(__file__).resolve().parent.parent
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
NODE = "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
UV = "astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884"
ATTEST = "actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be"
UPLOAD = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
DOWNLOAD = "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333"
CACHE_RESTORE = "actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9"
CACHE_SAVE = "actions/cache/save@55cc8345863c7cc4c66a329aec7e433d2d1c52a9"
# Runner images for each profile's quality job; every other profile uses Linux. The cache warm job builds the same set.
QUALITY_OS = {"ejm-harness": ["ubuntu-24.04", "macos-15", "windows-2025"], "ejm-cli": ["ubuntu-24.04", "macos-15"], "ejm-ide": ["macos-15"]}
# Cargo target directory each gate job builds, per profile. Only these profiles get a trusted build cache,
# keyed by the Cargo.lock beside each target directory.
RUST_TARGETS = {"quality": {"ejm-cli": "product/target", "ejm-harness": "product/target", "ejm-ide": "product/src-tauri/target",
                            "ejm-ui": "product/crates/ejm-tui/target"},
                "registry": {"ejm-harness": "product/registry/target"}}
RUST_VERSION = "1.99.1"
# The repositories' .cargo/config.toml caps local builds at two jobs; hosted runners use every core.
CARGO_ENV = {"CARGO_BUILD_JOBS": "default", "CARGO_INCREMENTAL": "0"}

def yaml(value: dict[str, Any] | list[Any], indent: int = 0) -> str:
    """Emit the limited maps, lists and strings used here, without dependencies."""
    pad = " " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            name = json.dumps(key)
            if isinstance(item, (dict, list)) and item:
                lines.append(pad + name + ":\n" + yaml(item, indent + 2))
            elif isinstance(item, str) and "\n" in item:
                lines.append(pad + name + ": |\n" + "\n".join(" " * (indent + 2) + line if line else "" for line in item.rstrip().splitlines()))
            else:
                lines.append(pad + name + ": " + json.dumps(item))
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(pad + "-\n" + yaml(item, indent + 2) if isinstance(item, dict) else pad + "- " + json.dumps(item) for item in value)
    raise TypeError(type(value))


def source(name: str, *, library: bool = False) -> str:
    text = (ROOT / "scripts" / name).read_text()
    return text.split('\nif __name__ == "__main__":')[0] if library else text


def python(text: str, args: str = "", executable: str = "python3") -> str:
    # GitHub evaluates expressions even inside quoted script strings. Encoding the
    # trusted library preserves literal consumer expressions without evaluating them.
    encoded = base64.b64encode(text.encode()).decode()
    return executable + " - " + args + " <<'TRUSTED_PYTHON'\nimport base64\nexec(compile(base64.b64decode('" + encoded + "'), 'trusted-workflow.py', 'exec'))\nTRUSTED_PYTHON\n"


def run(name: str, script: str, **extra: str | bool | int | dict[str, Any] | list[Any]) -> dict[str, Any]:
    return {"name": name, "shell": "bash", "run": script, **extra}


def checkout(path: str, ref: str, **extra: str | bool | int | dict[str, Any] | list[Any]) -> dict[str, Any]:
    return {"uses": CHECKOUT, "with": {"path": path, "ref": ref, "persist-credentials": False, "fetch-depth": 1, "submodules": False, **extra}}


ENV = {"PR_NUMBER": "${{ needs.admission.outputs.pr }}", "PR_HEAD": "${{ needs.admission.outputs.head }}", "PR_BASE": "${{ needs.admission.outputs.base }}", "ADMISSION_ID": "${{ needs.admission.outputs.admission }}", "GH_TOKEN": "${{ github.token }}"}
VERIFY = run("Recheck current human admission", python(source("governance.py"), "verify"))
REJECT_DEBUG = run("Require private review logs", python("""import os
if os.environ.get('RUNNER_DEBUG') == '1':
    raise SystemExit('Runner diagnostics must be disabled for review')
"""))
ARTIFACT = {"uses": DOWNLOAD, "with": {"artifact-ids": "${{ needs.prepare.outputs.artifact }}", "merge-multiple": True, "path": "prepared"}}
EXTRACT = run("Extract source data safely", python(source("extract.py"), "", "python3 -I"))
INSTALL_TOOLS = python(source("tools.py"), "cargo-deny cargo-machete", "python3 -I")
RUST_TOOLS = run("Install pinned Rust tools", """if [[ "$PROFILE" == ejm-* ]]; then
  rustup toolchain install """ + RUST_VERSION + """ --profile minimal --component clippy,rustfmt
  rustup default """ + RUST_VERSION + """
  if [[ "$PROFILE" != ejm-ui ]]; then
""" + INSTALL_TOOLS + """  fi
fi
""")


def owned(command: str) -> str:
    """Shell test for a product's own gate command: a regular, executable file that is not a symlink."""
    path = ".github/" + command
    return f"[[ ! -L .github && ! -L {path} && -f {path} && -x {path} ]]"


# The product owns its gate: an executable .github/quality replaces the profile's built-in commands below,
# which remain only as the transitional fallback. Toolchains and the shared ejm-ui sibling install stay here.
GATE = run("Run the project's required gate without secrets or write tokens", """cd product
if [[ -d ../ejm-ui ]]; then
  npm --prefix ../ejm-ui ci --ignore-scripts
fi
if """ + owned("quality") + """; then
  export npm_config_ignore_scripts=true
  ./.github/quality
else
  case "$PROFILE" in
    ejm-cli) ./scripts/check ;;
    ejm-harness) npm ci --ignore-scripts; npm --prefix registry ci --ignore-scripts; ./scripts/check ;;
    ejm-ide) npm ci --ignore-scripts; npm run verify; npm run site:check; npm run site:build ;;
    ejm-ui)
      export npm_config_ignore_scripts=true
      npm ci --ignore-scripts
      npm rebuild node-pty --ignore-scripts=false
      npm run check
      npm run build
      npm run check:rust
      node scripts/pack-proof.mjs
      ;;
    ejmlabs) node scripts/check.mjs; npm --prefix site test; npm --prefix site run build ;;
    .github) python3 -m unittest discover -s tests -v; python3 scripts/build_workflows.py --check ;;
    *) exit 1 ;;
  esac
fi
""")
REGISTRY = run("Run separate registry gate when applicable", """if [[ "$PROFILE" == ejm-harness ]]; then
  rustup toolchain install """ + RUST_VERSION + """ --profile minimal --component clippy,rustfmt --target wasm32-unknown-unknown
  rustup default """ + RUST_VERSION + """
""" + INSTALL_TOOLS + """  cargo install worker-build --version 0.8.7 --locked
  cd product
  if [[ -d ../ejm-ui ]]; then
    npm --prefix ../ejm-ui ci --ignore-scripts
  fi
  if """ + owned("quality-registry") + """; then
    export npm_config_ignore_scripts=true
    ./.github/quality-registry
  else
    npm ci --ignore-scripts
    npm --prefix registry ci --ignore-scripts
    ./scripts/check-registry
  fi
fi
""")


def build_steps(profile: str) -> list[dict[str, Any]]:
    """Toolchain and gate steps shared by the quality job and the cache warm job, so both build the same artifacts."""
    # The gate never saves a cache, so setup-uv's own cache save is off too.
    return [{"uses": NODE, "with": {"node-version": "24"}}, {"uses": UV, "with": {"version": "0.9.26", "enable-cache": False}},
            run("Install Linux harness keyring build prerequisites", """sudo apt-get update
sudo apt-get install --yes --no-install-recommends pkg-config libdbus-1-dev
""", **{"if": "${{ " + profile + " == 'ejm-harness' && runner.os == 'Linux' }}"}),
            RUST_TOOLS,
            {"name": "Prepare ejm-cli remote test prerequisites", "if": "${{ " + profile + " == 'ejm-cli' }}", "uses": "./product/.github/actions/setup-ci"},
            GATE]


def os_matrix(profile: str) -> str:
    choices = "".join(profile + " == '" + name + "' && '" + json.dumps(images, separators=(",", ":")) + "' || " for name, images in QUALITY_OS.items())
    return "${{ fromJSON(" + choices + "'[\"ubuntu-24.04\"]') }}"


def cache_prefix(job: str) -> str:
    """Start of every cache key of a gate job. A new toolchain or runner OS never reuses an older entry."""
    return "gate-" + job + "-${{ runner.os }}-rust" + RUST_VERSION + "-"


def rust_cache(job: str, profile: str) -> tuple[str, dict[str, str]]:
    """Return the condition and inputs of a job's Cargo cache, keyed by toolchain and the lockfile beside the target directory.

    The lockfile paths exist in the same layout after the gate extracts its sources and after the warm job checks them out.
    """
    targets = RUST_TARGETS[job]
    condition = "contains(fromJSON('" + json.dumps(sorted(targets), separators=(",", ":")) + "'), " + profile + ")"
    target = "${{ fromJSON('" + json.dumps(targets, separators=(",", ":")) + "')[" + profile + "] }}"
    locks = {name: path.removesuffix("/target") + "/Cargo.lock" for name, path in targets.items()}
    lock = "${{ hashFiles(fromJSON('" + json.dumps(locks, separators=(",", ":")) + "')[" + profile + "]) }}"
    return condition, {"path": "~/.cargo/registry/index\n~/.cargo/registry/cache\n~/.cargo/git/db\n" + target + "\n", "key": cache_prefix(job) + lock}


def restore(job: str) -> list[dict[str, Any]]:
    """Restore main's build for this lockfile, or its newest build for the same toolchain. The gate never saves."""
    condition, cache = rust_cache(job, "needs.admission.outputs.profile")
    return [{"uses": CACHE_RESTORE, "if": "${{ " + condition + " }}", "with": {**cache, "restore-keys": cache_prefix(job)}}]


def governance() -> dict[str, Any]:
    templates = {path.name: path.read_text() for path in sorted((ROOT / "templates/community").glob("*.md"))}
    standards_check = source("standards.py", library=True) + "\nstandards(Path(sys.argv[1]), sys.argv[2], " + repr(templates) + ")\n"
    pull_if = (
        "github.event_name == 'pull_request' && "
        "contains(fromJSON('[\"opened\",\"reopened\",\"synchronize\",\"ready_for_review\",\"converted_to_draft\",\"labeled\"]'), github.event.action) && "
        "(github.event.action != 'labeled' || github.event.label.name == 'gate:approve' || github.event.label.name == 'gate:revoke')"
    )
    admission = {
        "if": "${{ github.run_attempt == 1 && (" + pull_if + ") }}",
        "runs-on": "ubuntu-24.04", "timeout-minutes": 3,
        "permissions": {"contents": "read", "pull-requests": "write", "statuses": "write", "actions": "write"},
        "concurrency": {
            "group": "gate-${{ github.repository }}-${{ github.event.pull_request.number }}",
            "cancel-in-progress": True,
        },
        "outputs": {key: "${{ steps.admit.outputs." + key + " }}" for key in ("run", "pr", "head", "base", "admission", "profile")},
        "steps": [run("Admit from PR state or handle gate labels", python(source("governance.py"), "admit"), id="admit", env={"GH_TOKEN": "${{ github.token }}"})],
    }
    prepare = {
        "needs": "admission", "if": "${{ github.run_attempt == 1 && needs.admission.outputs.run == 'true' }}",
        "runs-on": "ubuntu-24.04", "timeout-minutes": 5, "permissions": {"contents": "read", "pull-requests": "read", "statuses": "read"}, "env": ENV,
        "outputs": {"artifact": "${{ steps.sources.outputs.artifact-id }}"},
        "steps": [REJECT_DEBUG, VERIFY, checkout("product", "${{ needs.admission.outputs.head }}"), checkout("base", "${{ needs.admission.outputs.base }}"),
                  run("Select the admitted harness dependency against trusted source authority", python(source("prepare.py"), "select-harness"),
                      id="harness", env={"PROFILE": "${{ needs.admission.outputs.profile }}", "HARNESS_READ_TOKEN": "${{ secrets.EJM_HARNESS_TOKEN || github.token }}"}),
                  {"uses": CHECKOUT, "if": "${{ steps.harness.outputs.revision != '' }}", "with": {"repository": "ejmlabs/ejm-harness", "ref": "${{ steps.harness.outputs.revision }}", "path": "harness", "persist-credentials": False, "token": "${{ secrets.EJM_HARNESS_TOKEN || github.token }}"}},
                  run("Read optional public UI dependency from trusted main", python(source("prepare.py"), "ui-pin"), id="ui"),
                  {"uses": CHECKOUT, "if": "${{ steps.ui.outputs.revision != '' }}", "with": {"repository": "ejmlabs/ejm-ui", "ref": "${{ steps.ui.outputs.revision }}", "path": "ejm-ui", "persist-credentials": False, "fetch-depth": 1, "submodules": False}},
                  run("Archive admitted source", python(source("prepare.py"))), VERIFY,
                  {"uses": UPLOAD, "id": "sources", "with": {"name": "admitted-sources", "path": "prepared/", "retention-days": 3, "if-no-files-found": "error"}}],
    }
    quality = {
        "needs": ["admission", "prepare"], "if": "${{ github.run_attempt == 1 }}", "runs-on": "${{ matrix.os }}", "timeout-minutes": 45, "permissions": {},
        "strategy": {"fail-fast": False, "matrix": {"os": os_matrix("needs.admission.outputs.profile")}},
        "env": {**CARGO_ENV, "PROFILE": "${{ needs.admission.outputs.profile }}", "CI": "true"},
        "steps": [ARTIFACT, EXTRACT, *restore("quality"), *build_steps("needs.admission.outputs.profile")],
    }
    registry = {
        "needs": ["admission", "prepare"], "if": "${{ github.run_attempt == 1 }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 25, "permissions": {},
        "env": {**CARGO_ENV, "PROFILE": "${{ needs.admission.outputs.profile }}"},
        "steps": [ARTIFACT, EXTRACT, *restore("registry"), {"uses": NODE, "if": "${{ needs.admission.outputs.profile == 'ejm-harness' }}", "with": {"node-version": "24"}}, REGISTRY],
    }
    standards = {
        "needs": ["admission", "prepare"], "if": "${{ github.run_attempt == 1 }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 3, "permissions": {},
        "env": {"PROFILE": "${{ needs.admission.outputs.profile }}"},
        "steps": [ARTIFACT, EXTRACT, run("Validate shared public standards and version metadata", python(standards_check, 'product "$PROFILE"'))],
    }
    finish = {"needs": ["admission", "prepare", "quality", "registry", "standards"],
              "if": "${{ github.run_attempt == 1 && always() && needs.admission.outputs.run == 'true' }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 3,
              "permissions": {"contents": "read", "pull-requests": "write", "statuses": "write"},
              "env": {**ENV, "JOB_RESULTS": "${{ toJSON(needs) }}"},
              "steps": [run("Publish required results only after live admission validation", python(source("governance.py"), "finish"))]}
    # Keep XAI_API_KEY declared optional and unused so the live pin's standards
    # scaffold check still passes; the next shared revision drops it.
    secrets = {"XAI_API_KEY": {"required": False}, "EJM_HARNESS_TOKEN": {"required": False}}
    return {"name": "Human-admitted PR checks", "on": {"workflow_call": {"secrets": secrets}}, "permissions": {}, "jobs": {"admission": admission, "prepare": prepare, "quality": quality, "registry": registry, "standards": standards, "finish": finish}}


def release_workflow() -> dict[str, Any]:
    inputs = {"commit": {"required": True, "type": "string"}, "version": {"required": True, "type": "string"}, "standards-ref": {"required": True, "type": "string"}}
    # Embed libraries, not their command entry points, before the release entry point.
    code = source("governance.py", library=True) + "\n" + source("standards.py", library=True) + "\n" + source("prepare.py", library=True) + "\n" + source("release.py")
    return {"name": "Checked draft source release", "on": {"workflow_call": {"inputs": inputs}}, "permissions": {},
            "concurrency": {"group": "draft-release-${{ github.repository }}", "cancel-in-progress": False},
            "jobs": {"draft": {"if": "${{ github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 8,
                               "permissions": {"contents": "write", "pull-requests": "read", "statuses": "read"},
                               "env": {"GH_TOKEN": "${{ github.token }}", "RELEASE_COMMIT": "${{ inputs.commit }}", "RELEASE_VERSION": "${{ inputs.version }}", "STANDARDS_REF": "${{ inputs.standards-ref }}"},
                               "steps": [checkout("product", "${{ inputs.commit }}"), run("Validate protected source and prepare assets without executing project code", python(code)),
                                         run("Create a new tag and draft release without replacing anything", """python3 - <<'PY'
import json, os, subprocess
from pathlib import Path
manifest = json.loads(Path('release-assets/provenance.json').read_text())
tag = 'v' + manifest['version']
repo = os.environ['GITHUB_REPOSITORY']
# VERSION is already validated; hyphens in build metadata do not mark prereleases.
prerelease_flags = ['--prerelease', '--latest=false'] if '-' in manifest['version'].split('+', 1)[0] else []
# No --force, --clobber, or implicit existing-tag acceptance.
subprocess.run(['gh', 'api', '--method', 'POST', 'repos/' + repo + '/git/refs', '-f', 'ref=refs/tags/' + tag, '-f', 'sha=' + manifest['commit']], check=True)
subprocess.run(['gh', 'release', 'create', tag, '--repo', repo, '--verify-tag', '--draft', '--title', tag, '--notes-file', 'release-notes.md', *prerelease_flags, *[str(p) for p in sorted(Path('release-assets').iterdir())]], check=True)
PY
""")]}}}


def build_inputs(*extra: str) -> dict[str, Any]:
    names = ("commit", "build-workflow", "build-run-id", *extra)
    return {name: {"required": False, "default": False, "type": "boolean"} if name == "attest" else {"required": True, "type": "string"} for name in names}


def build_env(inputs: dict[str, Any]) -> dict[str, Any]:
    env = {"GH_TOKEN": "${{ github.token }}", "RELEASE_COMMIT": "${{ inputs.commit }}", "BUILD_WORKFLOW": "${{ inputs.build-workflow }}", "BUILD_RUN_ID": "${{ inputs.build-run-id }}"}
    return {**env, "RELEASE_VERSION": "${{ inputs.version }}"} if "version" in inputs else env


def verify_build_workflow() -> dict[str, Any]:
    """Pre-tag gate: no checkout, no project code, read-only."""
    inputs = build_inputs()
    code = source("governance.py", library=True) + "\n" + source("standards.py", library=True) + "\n" + source("attach.py")
    return {"name": "Verified build run", "on": {"workflow_call": {"inputs": inputs}}, "permissions": {},
            "jobs": {"verify": {"runs-on": "ubuntu-24.04", "timeout-minutes": 3, "permissions": {"actions": "read"}, "env": build_env(inputs),
                                "steps": [run("Require a successful build of this commit from main", python(code, "verify", "python3 -I"))]}}}


def attach_workflow() -> dict[str, Any]:
    """The only job that holds the release write token. It checks out and runs no project code."""
    inputs = build_inputs("version", "attest")
    code = source("governance.py", library=True) + "\n" + source("standards.py", library=True) + "\n" + source("attach.py")
    return {"name": "Attach verified build files", "on": {"workflow_call": {"inputs": inputs}}, "permissions": {},
            "concurrency": {"group": "attach-assets-${{ github.repository }}", "cancel-in-progress": False},
            "jobs": {"attach": {"runs-on": "ubuntu-24.04", "timeout-minutes": 10,
                                "permissions": {"contents": "write", "actions": "read", "id-token": "write", "attestations": "write"}, "env": build_env(inputs),
                                "steps": [run("Require the build run, tag and draft release to match", python(code, "check", "python3 -I")),
                                          {"uses": DOWNLOAD, "with": {"name": "release-files", "run-id": "${{ inputs.build-run-id }}", "github-token": "${{ github.token }}", "path": "built"}},
                                          run("Recompute digests and attach to the draft", python(code, "attach", "python3 -I")),
                                          {"uses": ATTEST, "if": "${{ inputs.attest }}", "with": {"subject-path": "built/*", "show-summary": False}}]}}}


DEPENDENCY = {"persist-credentials": False, "fetch-depth": 1, "submodules": False}


def deploy_workflow() -> dict[str, Any]:
    """Build a site once without credentials, deploy it to staging, then deploy the same files to production after a human approves."""
    profile = "github.event.repository.name"
    push = "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}"
    build = 'cd product\ncase "$PROFILE" in\n' + "".join(
        "  " + name + ")\n" + "".join("    " + line + "\n" for line in commands.splitlines()) + '    tar -cf "$RUNNER_TEMP/site.tar" ' + " ".join(files) + "\n    ;;\n"
        for name, (commands, _, files) in SITES.items()) + "  *) exit 1 ;;\nesac\n"
    manifest, lock = ((ROOT / "deploy" / name).read_text() for name in ("package.json", "package-lock.json"))
    install = 'mkdir -p "$RUNNER_TEMP/deployer"\ncd "$RUNNER_TEMP/deployer"\n' + python(
        "from pathlib import Path\nPath('package.json').write_text(" + repr(manifest) + ")\nPath('package-lock.json').write_text(" + repr(lock) + ")\n"
    ) + "npm ci --ignore-scripts --no-audit --no-fund\n"

    def deploy(environment: str, needs: str, permissions: dict[str, str], env: dict[str, str]) -> dict[str, Any]:
        return {"needs": needs, "if": push, "runs-on": "ubuntu-24.04", "timeout-minutes": 10, "environment": environment, "permissions": permissions,
                # A newer main commit replaces a production deploy still waiting for approval; staging deploys run in order.
                "concurrency": {"group": "deploy-" + environment + "-${{ github.repository }}", "cancel-in-progress": environment == "production"},
                "env": {"PROFILE": "${{ " + profile + " }}"},
                "steps": [{"uses": DOWNLOAD, "with": {"name": "site", "path": "artifact"}}, {"uses": NODE, "with": {"node-version": "24"}},
                          run("Install the pinned deployer", install, env={"GH_TOKEN": "", "GITHUB_TOKEN": "", "NPM_CONFIG_USERCONFIG": "/dev/null"}),
                          run("Deploy the built site to " + environment, python(source("deploy.py"), environment, "python3 -I"),
                              env={"CLOUDFLARE_API_TOKEN": "${{ secrets.CLOUDFLARE_API_TOKEN }}", **env})]}

    jobs = {
        "build": {"if": push, "runs-on": "ubuntu-24.04", "timeout-minutes": 20, "permissions": {"contents": "read"}, "env": {"PROFILE": "${{ " + profile + " }}"},
                  "steps": [checkout("product", "${{ github.sha }}"),
                            run("Read main's reviewed dependency pins", python(source("prepare.py"), "warm-pins"), id="pins"),
                            {"uses": CHECKOUT, "if": "${{ steps.pins.outputs.ui != '' }}",
                             "with": {"repository": "ejmlabs/ejm-ui", "ref": "${{ steps.pins.outputs.ui }}", "path": "ejm-ui", **DEPENDENCY}},
                            {"uses": NODE, "with": {"node-version": "24"}},
                            run("Build the site without credentials", build),
                            {"uses": UPLOAD, "with": {"name": "site", "path": "${{ runner.temp }}/site.tar", "retention-days": 7, "if-no-files-found": "error"}}]},
        "staging": deploy("staging", "build", {}, {}),
        # Reads the environment's rules so a missing or unprotected production environment fails instead of deploying.
        "production": deploy("production", "staging", {"actions": "read"}, {"GH_TOKEN": "${{ github.token }}"}),
    }
    return {"name": "Deploy site", "on": {"workflow_call": {}}, "permissions": {}, "jobs": jobs}


def warm_workflow() -> dict[str, Any]:
    """The only writer of gate build caches: it builds reviewed main in the gate's layout and saves a cache that does not exist yet.

    A cache saved from a pull request run is scoped to that pull request, so only main's entries reach the gate.
    """
    profile = "github.event.repository.name"
    sources = [checkout("product", "${{ github.sha }}"),
               run("Read main's reviewed dependency pins", python(source("prepare.py"), "warm-pins"), id="pins"),
               {"uses": CHECKOUT, "if": "${{ steps.pins.outputs.harness != '' }}",
                "with": {"repository": "ejmlabs/ejm-harness", "ref": "${{ steps.pins.outputs.harness }}", "path": "ejm-harness", **DEPENDENCY}},
               {"uses": CHECKOUT, "if": "${{ steps.pins.outputs.ui != '' }}",
                "with": {"repository": "ejmlabs/ejm-ui", "ref": "${{ steps.pins.outputs.ui }}", "path": "ejm-ui", **DEPENDENCY}},
               # The gate builds exported archives, so the warm build must not see Git metadata either.
               run("Match the gate's exported source layout", "rm -rf product/.git ejm-harness/.git ejm-ui/.git\n")]

    def job(name: str, steps: list[dict[str, Any]], extra: dict[str, Any]) -> dict[str, Any]:
        condition, cache = rust_cache(name, profile)
        # Toolchain and setup steps keep the gate's exact form, since the CLI setup hook must; only the build itself is skipped on a hit.
        missing = "${{ steps.lookup.outputs.cache-hit != 'true' }}"
        return {"if": "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' && " + condition + " }}", **extra, "permissions": {"contents": "read"},
                "steps": [*sources, {"uses": CACHE_RESTORE, "id": "lookup", "with": {**cache, "lookup-only": True}},
                          *[{**step, "if": missing} if step in (GATE, REGISTRY) else step for step in steps],
                          # Only a build that passed is saved, because a saved key is never replaced and a hit skips the next build.
                          {"uses": CACHE_SAVE, "if": missing, "with": cache}]}

    quality = job("quality", build_steps(profile), {"runs-on": "${{ matrix.os }}", "timeout-minutes": 45, "strategy": {"fail-fast": False, "matrix": {"os": os_matrix(profile)}},
                                                     "env": {**CARGO_ENV, "PROFILE": "${{ " + profile + " }}", "CI": "true"}})
    registry = job("registry", [{"uses": NODE, "if": "${{ " + profile + " == 'ejm-harness' }}", "with": {"node-version": "24"}}, REGISTRY],
                   {"runs-on": "ubuntu-24.04", "timeout-minutes": 25, "env": {**CARGO_ENV, "PROFILE": "${{ " + profile + " }}"}})
    # Runs queue instead of cancelling each other: a cache is saved only by a build that finishes, and a queued run
    # whose cache already exists finishes quickly. GitHub keeps only the newest queued run.
    return {"name": "Warm trusted gate build caches", "on": {"workflow_call": {}}, "permissions": {},
            "concurrency": {"group": "warm-cache-${{ github.repository }}", "cancel-in-progress": False},
            "jobs": {"quality": quality, "registry": registry}}


def main() -> None:
    for name, data in (("governance.yml", governance()), ("draft-release.yml", release_workflow()), ("verify-build.yml", verify_build_workflow()), ("attach-assets.yml", attach_workflow()),
                       ("warm-cache.yml", warm_workflow()), ("deploy-site.yml", deploy_workflow())):
        path = ROOT / ".github/workflows" / name
        expected = "# Generated by scripts/build_workflows.py. Edit scripts and regenerate.\n" + yaml(data) + "\n"
        if "--check" in sys.argv:
            if not path.exists() or path.read_text() != expected:
                raise SystemExit(f"Stale generated workflow: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected)


if __name__ == "__main__":
    main()
