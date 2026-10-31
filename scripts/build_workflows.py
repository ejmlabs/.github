#!/usr/bin/env python3
"""Embed trusted scripts in reusable workflows so private callers need no read token."""
import base64
import json
import re
import sys
from pathlib import Path
from typing import Any

from deploy import SITES, source_path

ROOT = Path(__file__).resolve().parent.parent


def action_pins(manifest: Path) -> dict[str, str]:
    """Read the action pins from action.yml, the manifest Dependabot updates beside the generated workflows."""
    text = manifest.read_text()
    found = re.findall(r"(?m)^ +(?:- )?uses: ([A-Za-z0-9][A-Za-z0-9._/-]*)@([0-9a-f]{40})(?: +#.*)?$", text)
    names = [name for name, _ in found]
    if len(found) != text.count("uses:") or len(set(names)) != len(names):
        raise ValueError("action.yml must list each action once, pinned to a full commit SHA")
    return {name: name + "@" + sha for name, sha in found}


PINS = action_pins(ROOT / "action.yml")
CHECKOUT, NODE, UV, ATTEST = PINS["actions/checkout"], PINS["actions/setup-node"], PINS["astral-sh/setup-uv"], PINS["actions/attest-build-provenance"]
UPLOAD, DOWNLOAD, CACHE_RESTORE, CACHE_SAVE = PINS["actions/upload-artifact"], PINS["actions/download-artifact"], PINS["actions/cache/restore"], PINS["actions/cache/save"]
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


def libraries(*names: str) -> str:
    """Join library scripts into one namespace, in dependency order. Each workflow embeds only the libraries it uses."""
    return "\n".join(source(name, library=True) for name in names)


def python(text: str, args: str = "", executable: str = "python3 -I") -> str:
    # GitHub evaluates expressions even inside quoted script strings. Encoding the
    # trusted library preserves literal consumer expressions without evaluating them.
    # -I keeps the working directory (which holds admitted sources) and PYTHON* variables out of imports.
    encoded = base64.b64encode(text.encode()).decode()
    return executable + " - " + args + " <<'TRUSTED_PYTHON'\nimport base64\nexec(compile(base64.b64decode('" + encoded + "'), 'trusted-workflow.py', 'exec'))\nTRUSTED_PYTHON\n"


def run(name: str, script: str, **extra: str | bool | int | dict[str, Any] | list[Any]) -> dict[str, Any]:
    return {"name": name, "shell": "bash", "run": script, **extra}


def checkout(path: str, ref: str, **extra: str | bool | int | dict[str, Any] | list[Any]) -> dict[str, Any]:
    return {"uses": CHECKOUT, "with": {"path": path, "ref": ref, "persist-credentials": False, "fetch-depth": 1, "submodules": False, **extra}}


ENV = {"PR_NUMBER": "${{ needs.admission.outputs.pr }}", "PR_HEAD": "${{ needs.admission.outputs.head }}", "PR_BASE": "${{ needs.admission.outputs.base }}", "GH_TOKEN": "${{ github.token }}"}
VERIFY = run("Recheck current human admission", python(source("governance.py"), "verify"))
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


# The shared agent skills and house rules a repository must hold are the templates at the commit of this workflow,
# the caller's pin, so they move only when the pin does. The repository is public: plain git, no token, no credential
# helper. This repository checks its own copies against its own templates, which the same PR may change.
# GitHub reads the job context in step env, never in a job's own env, so each step sets WORKFLOW_SHA itself.
SHARED_TEMPLATES = run("Fetch the shared agent templates at this workflow's commit", """if [[ "$WORKFLOW_REPOSITORY" != ejmlabs/.github || ! "$WORKFLOW_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::The shared gate must run from ejmlabs/.github at a full commit SHA"
  exit 1
fi
git init -q shared
git -C shared -c credential.helper= fetch -q --depth 1 --no-tags https://github.com/ejmlabs/.github.git "$WORKFLOW_SHA"
git -C shared -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
""", env={"WORKFLOW_REPOSITORY": "${{ job.workflow_repository }}", "WORKFLOW_SHA": "${{ job.workflow_sha }}", "GIT_TERMINAL_PROMPT": "0"})
SHARED_TEMPLATES["if"] = "${{ needs.admission.outputs.profile != '.github' }}"
AGENT_SYNC = run("Check the shared agent skills and house rules", """templates=shared/templates/agents
if [[ "$PROFILE" == .github ]]; then
  templates=product/templates/agents
fi
trap 'echo "::error::Shared agent files differ from ejmlabs/.github at $WORKFLOW_SHA. From a checkout of that commit, run: python3 scripts/sync_agents.py PATH_TO_THIS_REPOSITORY"' ERR
""" + python(source("sync_agents.py"), '--check --templates "$templates" product'), env={"WORKFLOW_SHA": "${{ job.workflow_sha }}"})


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
    standards_check = libraries("versioning.py", "standards.py") + "\nsys.exit(standards_main(sys.argv[1:]))\n"
    pull_if = (
        "github.event_name == 'pull_request' && "
        "contains(fromJSON('[\"opened\",\"reopened\",\"synchronize\",\"ready_for_review\",\"converted_to_draft\",\"labeled\"]'), github.event.action) && "
        "(github.event.action != 'labeled' || github.event.label.name == 'gate:approve' || github.event.label.name == 'gate:revoke')"
    )
    admission = {
        "if": "${{ " + pull_if + " }}",
        "runs-on": "ubuntu-24.04", "timeout-minutes": 3,
        "permissions": {"contents": "read", "pull-requests": "write", "statuses": "write", "actions": "write"},
        "concurrency": {
            "group": "gate-${{ github.repository }}-${{ github.event.pull_request.head.sha }}",
            "cancel-in-progress": False,
        },
        "outputs": {key: "${{ steps.admit.outputs." + key + " }}" for key in ("run", "pr", "head", "base", "profile")},
        "steps": [run("Admit from PR state or handle gate labels", python(source("governance.py"), "admit"), id="admit", env={"GH_TOKEN": "${{ github.token }}"})],
    }
    prepare = {
        "needs": "admission", "if": "${{ needs.admission.outputs.run == 'true' }}",
        "runs-on": "ubuntu-24.04", "timeout-minutes": 5, "permissions": {"contents": "read", "pull-requests": "read", "statuses": "read"}, "env": ENV,
        "outputs": {"artifact": "${{ steps.sources.outputs.artifact-id }}"},
        "steps": [VERIFY, checkout("product", "${{ needs.admission.outputs.head }}"), checkout("base", "${{ needs.admission.outputs.base }}"),
                  run("Select the admitted harness dependency against trusted source authority", python(source("prepare.py"), "select-harness"),
                      id="harness", env={"PROFILE": "${{ needs.admission.outputs.profile }}", "HARNESS_READ_TOKEN": "${{ secrets.EJM_HARNESS_TOKEN || github.token }}"}),
                  {"uses": CHECKOUT, "if": "${{ steps.harness.outputs.revision != '' }}", "with": {"repository": "ejmlabs/ejm-harness", "ref": "${{ steps.harness.outputs.revision }}", "path": "harness", "persist-credentials": False, "token": "${{ secrets.EJM_HARNESS_TOKEN || github.token }}"}},
                  run("Read optional public UI dependency from trusted main", python(source("prepare.py"), "ui-pin"), id="ui"),
                  {"uses": CHECKOUT, "if": "${{ steps.ui.outputs.revision != '' }}", "with": {"repository": "ejmlabs/ejm-ui", "ref": "${{ steps.ui.outputs.revision }}", "path": "ejm-ui", "persist-credentials": False, "fetch-depth": 1, "submodules": False}},
                  run("Archive admitted source", python(source("prepare.py"))), VERIFY,
                  # One artifact per attempt: "Re-run all jobs" uploads again, and an artifact is never replaced by name.
                  {"uses": UPLOAD, "id": "sources", "with": {"name": "admitted-sources-${{ github.run_attempt }}", "path": "prepared/", "retention-days": 3, "if-no-files-found": "error"}}],
    }
    quality = {
        "needs": ["admission", "prepare"], "runs-on": "${{ matrix.os }}", "timeout-minutes": 45, "permissions": {},
        "strategy": {"fail-fast": False, "matrix": {"os": os_matrix("needs.admission.outputs.profile")}},
        "env": {**CARGO_ENV, "PROFILE": "${{ needs.admission.outputs.profile }}", "CI": "true"},
        "steps": [ARTIFACT, EXTRACT, *restore("quality"), *build_steps("needs.admission.outputs.profile")],
    }
    registry = {
        "needs": ["admission", "prepare"], "runs-on": "ubuntu-24.04", "timeout-minutes": 25, "permissions": {},
        "env": {**CARGO_ENV, "PROFILE": "${{ needs.admission.outputs.profile }}"},
        "steps": [ARTIFACT, EXTRACT, *restore("registry"), {"uses": NODE, "if": "${{ needs.admission.outputs.profile == 'ejm-harness' }}", "with": {"node-version": "24"}}, REGISTRY],
    }
    standards = {
        "needs": ["admission", "prepare"], "runs-on": "ubuntu-24.04", "timeout-minutes": 3, "permissions": {},
        "env": {"PROFILE": "${{ needs.admission.outputs.profile }}"},
        "steps": [ARTIFACT, EXTRACT, run("Validate shared public standards and version metadata", python(standards_check, 'product "$PROFILE"')),
                  SHARED_TEMPLATES, AGENT_SYNC],
    }
    finish = {"needs": ["admission", "prepare", "quality", "registry", "standards"],
              "if": "${{ !cancelled() && needs.admission.outputs.run == 'true' }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 3,
              "permissions": {"contents": "read", "pull-requests": "write", "statuses": "write"},
              "env": {**ENV, "JOB_RESULTS": "${{ toJSON(needs) }}"},
              "steps": [run("Publish required results only after live admission validation", python(source("governance.py"), "finish"))]}
    secrets = {"EJM_HARNESS_TOKEN": {"required": False}}
    return {"name": "Human-admitted PR checks", "on": {"workflow_call": {"secrets": secrets}}, "permissions": {}, "jobs": {"admission": admission, "prepare": prepare, "quality": quality, "registry": registry, "standards": standards, "finish": finish}}


def release_workflow() -> dict[str, Any]:
    inputs = {"commit": {"required": True, "type": "string"}, "version": {"required": True, "type": "string"}, "standards-ref": {"required": True, "type": "string"}}
    # Embed libraries, not their command entry points, before the release entry point.
    code = libraries("governance.py", "versioning.py", "standards.py", "prepare.py") + "\n" + source("release.py")
    return {"name": "Checked draft source release", "on": {"workflow_call": {"inputs": inputs}}, "permissions": {},
            "concurrency": {"group": "draft-release-${{ github.repository }}", "cancel-in-progress": False},
            "jobs": {"draft": {"if": "${{ github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 8,
                               "permissions": {"contents": "write", "pull-requests": "read", "statuses": "read"},
                               "env": {"GH_TOKEN": "${{ github.token }}", "RELEASE_COMMIT": "${{ inputs.commit }}", "RELEASE_VERSION": "${{ inputs.version }}", "STANDARDS_REF": "${{ inputs.standards-ref }}"},
                               "steps": [checkout("product", "${{ inputs.commit }}"), run("Validate protected source and prepare assets without executing project code", python(code)),
                                         run("Create a draft release without a tag, replacing nothing", """python3 - <<'PY'
import json, os, subprocess
from pathlib import Path
manifest = json.loads(Path('release-assets/provenance.json').read_text())
tag = 'v' + manifest['version']
repo = os.environ['GITHUB_REPOSITORY']
# VERSION is already validated; hyphens in build metadata do not mark prereleases.
prerelease_flags = ['--prerelease', '--latest=false'] if '-' in manifest['version'].split('+', 1)[0] else []
# No tag ref is written. The draft only targets the commit, and GitHub creates the tag when a human publishes it,
# so a failed run never burns a version. No --force, --clobber, or implicit existing-tag acceptance.
subprocess.run(['gh', 'release', 'create', tag, '--repo', repo, '--target', manifest['commit'], '--draft', '--title', tag, '--notes-file', 'release-notes.md', *prerelease_flags, *[str(p) for p in sorted(Path('release-assets').iterdir())]], check=True)
PY
""")]}}}


def build_inputs(*extra: str) -> dict[str, Any]:
    names = ("commit", "build-workflow", "build-run-id", *extra)
    return {name: {"required": False, "default": False, "type": "boolean"} if name == "attest" else {"required": True, "type": "string"} for name in names}


def build_env(inputs: dict[str, Any]) -> dict[str, Any]:
    env = {"GH_TOKEN": "${{ github.token }}", "RELEASE_COMMIT": "${{ inputs.commit }}", "BUILD_WORKFLOW": "${{ inputs.build-workflow }}", "BUILD_RUN_ID": "${{ inputs.build-run-id }}"}
    return {**env, "RELEASE_VERSION": "${{ inputs.version }}"} if "version" in inputs else env


def attach_code() -> str:
    """The attach script with the two libraries it needs: the API class and SemVer. The standards check stays out."""
    return libraries("governance.py", "versioning.py") + "\n" + source("attach.py")


def verify_build_workflow() -> dict[str, Any]:
    """Pre-draft gate: no checkout, no project code, read-only."""
    inputs = build_inputs()
    return {"name": "Verified build run", "on": {"workflow_call": {"inputs": inputs}}, "permissions": {},
            "jobs": {"verify": {"runs-on": "ubuntu-24.04", "timeout-minutes": 3, "permissions": {"actions": "read"}, "env": build_env(inputs),
                                "steps": [run("Require a successful build of this commit from main", python(attach_code(), "verify", "python3 -I"))]}}}


def attach_workflow() -> dict[str, Any]:
    """Two jobs. `attach` alone holds the release write token and runs no project code. `attest`, only on request, holds the
    attestation permissions and no write token for contents, and attests exactly the files `attach` verified and attached."""
    inputs = build_inputs("version", "attest")
    code = attach_code()
    artifact = {"uses": DOWNLOAD, "with": {"name": "release-files", "run-id": "${{ inputs.build-run-id }}", "github-token": "${{ github.token }}", "path": "built"}}
    attach = {"runs-on": "ubuntu-24.04", "timeout-minutes": 10, "permissions": {"contents": "write", "actions": "read"}, "env": build_env(inputs),
              "outputs": {"digests": "${{ steps.attached.outputs.digests }}"},
              "steps": [run("Require the build run and the draft release to match", python(code, "check", "python3 -I")), artifact,
                        run("Recompute digests and attach to the draft", python(code, "attach", "python3 -I"), id="attached")]}
    # Nothing here can write contents or releases. The digests come from the attach job's output and are recomputed from a fresh
    # download of the same artifact, so a changed or swapped file stops the job before the attestation is signed. The attach job
    # verified the run this job downloads from, and the confirm step checks the run again before it reads the files.
    attest = {"needs": "attach", "if": "${{ inputs.attest }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 10,
              "permissions": {"contents": "read", "actions": "read", "id-token": "write", "attestations": "write"},
              "env": {**build_env(build_inputs()), "ATTACHED_DIGESTS": "${{ needs.attach.outputs.digests }}"},
              "steps": [artifact, run("Require the files to equal the attached files", python(code, "confirm", "python3 -I")),
                        {"uses": ATTEST, "with": {"subject-path": "built/*", "show-summary": False}}]}
    return {"name": "Attach verified build files", "on": {"workflow_call": {"inputs": inputs}}, "permissions": {},
            "concurrency": {"group": "attach-assets-${{ github.repository }}", "cancel-in-progress": False},
            "jobs": {"attach": attach, "attest": attest}}


DEPENDENCY = {"persist-credentials": False, "fetch-depth": 1, "submodules": False}


def deploy_workflow() -> dict[str, Any]:
    """Build a site once without credentials, deploy it to staging, then deploy the same files to production after a human approves."""
    profile = "github.event.repository.name"
    push = "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}"
    # A product that owns .github/site-build builds with it; the profile's commands are the fallback. The files to pack stay in SITES.
    product_build = "[[ ! -L .github && ! -L .github/site-build && -f .github/site-build && -x .github/site-build ]]"
    commands = "".join("    " + name + ")\n" + "".join("      " + line + "\n" for line in build.splitlines()) + "      ;;\n" for name, (build, _, _) in SITES.items())
    packs = "".join("  " + name + ') tar -cf "$RUNNER_TEMP/site.tar" ' + " ".join(files) + " ;;\n" for name, (_, _, files) in SITES.items())
    build = ("cd product\nif " + product_build + "; then\n  export npm_config_ignore_scripts=true\n  ./.github/site-build\nelse\n"
             '  case "$PROFILE" in\n' + commands + "    *) exit 1 ;;\n  esac\nfi\n" + 'case "$PROFILE" in\n' + packs + "  *) exit 1 ;;\nesac\n")
    manifest, lock = ((ROOT / "deploy" / name).read_text() for name in ("package.json", "package-lock.json"))
    install = 'mkdir -p "$RUNNER_TEMP/deployer"\ncd "$RUNNER_TEMP/deployer"\n' + python(
        "from pathlib import Path\nPath('package.json').write_text(" + repr(manifest) + ")\nPath('package-lock.json').write_text(" + repr(lock) + ")\n"
    ) + "npm ci --ignore-scripts --no-audit --no-fund\n"
    # Each repository has one of these paths; the deploy compares the build's copy with the reviewed commit's, so only these are fetched.
    sparse: dict[str, str | bool] = {"sparse-checkout": "\n".join(sorted({"/" + source_path(name) for name in SITES})), "sparse-checkout-cone-mode": False}

    def deploy(environment: str, needs: str) -> dict[str, Any]:
        trusted = python(source("deploy.py"), "{mode} " + environment, "python3 -I")
        return {"needs": needs, "if": push, "runs-on": "ubuntu-24.04", "timeout-minutes": 10, "environment": environment,
                # contents reads the reviewed config; actions reads the environment's rules. Both fit within the caller's grant.
                "permissions": {"contents": "read", "actions": "read"},
                # A run that has started is never cancelled, so Wrangler is never stopped mid-deploy. A newer main commit waits behind it,
                # and GitHub keeps only the newest waiting run, so an older commit that never started is replaced.
                "concurrency": {"group": "deploy-" + environment + "-${{ github.repository }}", "cancel-in-progress": False},
                "env": {"PROFILE": "${{ " + profile + " }}"},
                "steps": [{"uses": DOWNLOAD, "with": {"name": "site", "path": "artifact"}},
                          # The Wrangler config and any Worker source come from this reviewed commit, as data. Nothing from it runs.
                          checkout("reviewed", "${{ github.sha }}", **sparse),
                          {"uses": NODE, "with": {"node-version": "24"}},
                          run("Install the pinned deployer", install, env={"GH_TOKEN": "", "GITHUB_TOKEN": "", "NPM_CONFIG_USERCONFIG": "/dev/null"}),
                          # GitHub creates a missing environment without rules, so read them before the deploy token is in play.
                          run("Require the " + environment + " environment's protections", trusted.replace("{mode}", "protection"), env={"GH_TOKEN": "${{ github.token }}"}),
                          run("Deploy the built site to " + environment, trusted.replace("{mode}", "deploy"),
                              env={"CLOUDFLARE_API_TOKEN": "${{ secrets.CLOUDFLARE_API_TOKEN }}"})]}

    jobs = {
        # Builds queue in push order too, so a slow build of an older commit cannot reach staging and production after a newer one.
        "build": {"if": push, "runs-on": "ubuntu-24.04", "timeout-minutes": 20, "permissions": {"contents": "read"}, "env": {"PROFILE": "${{ " + profile + " }}"},
                  "concurrency": {"group": "deploy-build-${{ github.repository }}", "cancel-in-progress": False},
                  "steps": [checkout("product", "${{ github.sha }}"),
                            run("Read main's reviewed dependency pins", python(source("prepare.py"), "warm-pins"), id="pins"),
                            {"uses": CHECKOUT, "if": "${{ steps.pins.outputs.ui != '' }}",
                             "with": {"repository": "ejmlabs/ejm-ui", "ref": "${{ steps.pins.outputs.ui }}", "path": "ejm-ui", **DEPENDENCY}},
                            {"uses": NODE, "with": {"node-version": "24"}},
                            run("Build the site without credentials", build),
                            {"uses": UPLOAD, "with": {"name": "site", "path": "${{ runner.temp }}/site.tar", "retention-days": 7, "if-no-files-found": "error"}}]},
        "staging": deploy("staging", "build"),
        "production": deploy("production", "staging"),
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
