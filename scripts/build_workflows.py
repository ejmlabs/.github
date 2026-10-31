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
# Cargo target directory each gate job builds, per profile. Only these profiles get a trusted build cache.
RUST_TARGETS = {"quality": {"ejm-cli": "product/target", "ejm-harness": "product/target", "ejm-ide": "product/src-tauri/target",
                            "ejm-ui": "product/crates/ejm-tui/target"},
                "registry": {"ejm-harness": "product/registry/target"}}
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
EXTRACT = run("Extract source data safely", """python3 - <<'PY'
import os
import tarfile
from pathlib import Path
for file in Path('prepared').glob('*.tar'):
    with tarfile.open(file) as archive:
        archive.extractall('.', filter='data')
        # Admitted sources must be newer than any restored build, so Cargo rebuilds every local crate.
        for member in archive.getmembers():
            if member.isfile():
                os.utime(member.name)
PY
""")
INSTALL_TOOLS = python(source("tools.py"), "cargo-deny cargo-machete", "python3 -I")
RUST_TOOLS = run("Install pinned Rust tools", """if [[ "$PROFILE" == ejm-* ]]; then
  rustup toolchain install 1.99.1 --profile minimal --component clippy,rustfmt
  rustup default 1.99.1
  if [[ "$PROFILE" != ejm-ui ]]; then
""" + INSTALL_TOOLS + """  fi
fi
""")
GATE = run("Run the project's required gate without secrets or write tokens", """cd product
if [[ -d ../ejm-ui ]]; then
  npm --prefix ../ejm-ui ci --ignore-scripts
fi
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
""")
REGISTRY = run("Run separate registry gate when applicable", """if [[ "$PROFILE" == ejm-harness ]]; then
  rustup toolchain install 1.99.1 --profile minimal --component clippy,rustfmt --target wasm32-unknown-unknown
  rustup default 1.99.1
""" + INSTALL_TOOLS + """  cargo install worker-build --version 0.8.7 --locked
  cd product
  if [[ -d ../ejm-ui ]]; then
    npm --prefix ../ejm-ui ci --ignore-scripts
  fi
  npm ci --ignore-scripts
  npm --prefix registry ci --ignore-scripts
  ./scripts/check-registry
fi
""")


def build_steps(profile: str) -> list[dict[str, Any]]:
    """Toolchain and gate steps shared by the quality job and the cache warm job, so both build the same artifacts."""
    return [{"uses": NODE, "with": {"node-version": "24"}}, {"uses": UV, "with": {"version": "0.9.26"}},
            run("Install Linux harness keyring build prerequisites", """sudo apt-get update
sudo apt-get install --yes --no-install-recommends pkg-config libdbus-1-dev
""", **{"if": "${{ " + profile + " == 'ejm-harness' && runner.os == 'Linux' }}"}),
            RUST_TOOLS,
            {"name": "Prepare ejm-cli remote test prerequisites", "if": "${{ " + profile + " == 'ejm-cli' }}", "uses": "./product/.github/actions/setup-ci"},
            GATE]


def os_matrix(profile: str) -> str:
    choices = "".join(profile + " == '" + name + "' && '" + json.dumps(images, separators=(",", ":")) + "' || " for name, images in QUALITY_OS.items())
    return "${{ fromJSON(" + choices + "'[\"ubuntu-24.04\"]') }}"


def rust_cache(job: str, profile: str, revision: str) -> tuple[str, dict[str, str]]:
    """Return the condition and inputs of a job's Cargo cache, keyed by the exact main commit that built it."""
    targets = RUST_TARGETS[job]
    condition = "contains(fromJSON('" + json.dumps(sorted(targets), separators=(",", ":")) + "'), " + profile + ")"
    target = "${{ fromJSON('" + json.dumps(targets, separators=(",", ":")) + "')[" + profile + "] }}"
    return condition, {"path": "~/.cargo/registry/index\n~/.cargo/registry/cache\n~/.cargo/git/db\n" + target + "\n",
                       "key": "gate-" + job + "-${{ runner.os }}-${{ " + revision + " }}"}


def restore(job: str) -> list[dict[str, Any]]:
    """Restore only the build main made at the admitted base; a prefix match or any other entry is deleted unused."""
    condition, cache = rust_cache(job, "needs.admission.outputs.profile", "needs.admission.outputs.base")
    return [{"uses": CACHE_RESTORE, "id": "cache", "if": "${{ " + condition + " }}", "with": cache},
            run("Discard any cache that is not main's exact build", 'rm -rf ~/.cargo/registry/index ~/.cargo/registry/cache ~/.cargo/git/db "$TARGET_DIR"\n',
                **{"if": "${{ " + condition + " && steps.cache.outputs.cache-hit != 'true' }}"}, env={"TARGET_DIR": cache["path"].splitlines()[-1]})]


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
                # A newer main commit replaces a production deploy still waiting for approval; staging deploys run in order.
                "concurrency": {"group": "deploy-" + environment + "-${{ github.repository }}", "cancel-in-progress": environment == "production"},
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
        "build": {"if": push, "runs-on": "ubuntu-24.04", "timeout-minutes": 20, "permissions": {"contents": "read"}, "env": {"PROFILE": "${{ " + profile + " }}"},
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
    """The only writer of gate build caches: it builds reviewed main, in the gate's layout, and saves what the gate may restore."""
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
        condition, cache = rust_cache(name, profile, "github.sha")
        return {"if": "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' && " + condition + " }}", **extra, "permissions": {"contents": "read"},
                "steps": [*sources, *steps, {"uses": CACHE_SAVE, "if": "${{ !cancelled() }}", "with": cache}]}

    quality = job("quality", build_steps(profile), {"runs-on": "${{ matrix.os }}", "timeout-minutes": 45, "strategy": {"fail-fast": False, "matrix": {"os": os_matrix(profile)}},
                                                     "env": {**CARGO_ENV, "PROFILE": "${{ " + profile + " }}", "CI": "true"}})
    registry = job("registry", [{"uses": NODE, "if": "${{ " + profile + " == 'ejm-harness' }}", "with": {"node-version": "24"}}, REGISTRY],
                   {"runs-on": "ubuntu-24.04", "timeout-minutes": 25, "env": {**CARGO_ENV, "PROFILE": "${{ " + profile + " }}"}})
    # A newer main commit makes the older warm build useless, since the gate restores only the exact base it admits.
    return {"name": "Warm trusted gate build caches", "on": {"workflow_call": {}}, "permissions": {},
            "concurrency": {"group": "warm-cache-${{ github.repository }}", "cancel-in-progress": True},
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
