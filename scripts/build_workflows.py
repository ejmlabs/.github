#!/usr/bin/env python3
"""Embed trusted scripts in reusable workflows so private callers need no read token."""
import json
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
NODE = "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
UV = "astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e"
UPLOAD = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
DOWNLOAD = "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"
# Provider settings are confined to these constants and the review-step key env.
REVIEWER_MODEL = "xai/grok-4.5"
REVIEWER_FALLBACK_MODELS = '[]'
REVIEWER_REASONING_EFFORT = "high"
REVIEWER_AI_TIMEOUT = 225
REVIEWER_JOB_TIMEOUT_MINUTES = 12

def yaml(value, indent=0):
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


def source(name, library=False):
    text = (ROOT / "scripts" / name).read_text()
    return text.split('\nif __name__ == "__main__":')[0] if library else text


def python(text, args="", executable="python3"):
    # GitHub evaluates expressions even inside quoted script strings. Encoding the
    # trusted library preserves literal consumer expressions without evaluating them.
    encoded = base64.b64encode(text.encode()).decode()
    return executable + " - " + args + " <<'TRUSTED_PYTHON'\nimport base64\nexec(compile(base64.b64decode('" + encoded + "'), 'trusted-workflow.py', 'exec'))\nTRUSTED_PYTHON\n"


def run(name, script, **extra):
    return {"name": name, "shell": "bash", "run": script, **extra}


def checkout(path, ref, **extra):
    return {"uses": CHECKOUT, "with": {"path": path, "ref": ref, "persist-credentials": False, "fetch-depth": 1, "submodules": False, **extra}}


ENV = {"PR_NUMBER": "${{ needs.admission.outputs.pr }}", "PR_HEAD": "${{ needs.admission.outputs.head }}", "PR_BASE": "${{ needs.admission.outputs.base }}", "ADMISSION_ID": "${{ needs.admission.outputs.admission }}", "GH_TOKEN": "${{ github.token }}"}
VERIFY = run("Recheck current human admission", python(source("governance.py"), "verify"))
REJECT_DEBUG = run("Require private review logs", python("""import os
if os.environ.get('RUNNER_DEBUG') == '1':
    raise SystemExit('Runner diagnostics must be disabled for review')
"""))
ARTIFACT = {"uses": DOWNLOAD, "with": {"artifact-ids": "${{ needs.prepare.outputs.artifact }}", "merge-multiple": True, "path": "prepared"}}
EXTRACT = run("Extract source data safely", """python3 - <<'PY'
import tarfile
from pathlib import Path
for file in Path('prepared').glob('*.tar'):
    with tarfile.open(file) as archive:
        archive.extractall('.', filter='data')
PY
""")


def governance():
    templates = {path.name: path.read_text() for path in sorted((ROOT / "templates/community").glob("*.md"))}
    standards_check = source("standards.py", True) + "\nstandards(Path(sys.argv[1]), sys.argv[2], " + repr(templates) + ")\n"
    admission = {
        "if": "${{ github.run_attempt == 1 && github.event_name == 'issue_comment' && github.event.issue.pull_request && contains(fromJSON('[\"OWNER\",\"MEMBER\",\"COLLABORATOR\"]'), github.event.comment.author_association) && ((github.event.action == 'created' && github.event.sender.type == 'User' && (startsWith(github.event.comment.body, '/ready ') || startsWith(github.event.comment.body, '/approve ') || startsWith(github.event.comment.body, '/revoke '))) || (github.event.action != 'created' && (startsWith(github.event.comment.body, '/ready ') || startsWith(github.event.comment.body, '/approve ') || startsWith(github.event.changes.body.from, '/ready ') || startsWith(github.event.changes.body.from, '/approve ')))) }}",
        "runs-on": "ubuntu-24.04", "timeout-minutes": 3,
        "permissions": {"contents": "read", "pull-requests": "write", "statuses": "write", "actions": "write"},
        "concurrency": {"group": "human-command-${{ github.repository }}-${{ github.event.issue.number }}", "cancel-in-progress": False},
        "outputs": {key: "${{ steps.admit.outputs." + key + " }}" for key in ("run", "pr", "head", "base", "admission", "profile")},
        "steps": [run("Validate live maintainer and commit; consume once", python(source("governance.py"), "admit"), id="admit", env={"GH_TOKEN": "${{ github.token }}"})],
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
        "strategy": {"fail-fast": False, "max-parallel": 2, "matrix": {"os": "${{ fromJSON(needs.admission.outputs.profile == 'ejm-harness' && '[\"ubuntu-24.04\",\"macos-15\",\"windows-2025\"]' || needs.admission.outputs.profile == 'ejm-cli' && '[\"ubuntu-24.04\",\"macos-15\"]' || needs.admission.outputs.profile == 'ejm-ide' && '[\"macos-15\"]' || '[\"ubuntu-24.04\"]') }}"}},
        "env": {"CARGO_BUILD_JOBS": "2", "CARGO_INCREMENTAL": "0", "PROFILE": "${{ needs.admission.outputs.profile }}", "CI": "true"},
        "steps": [ARTIFACT, EXTRACT, {"uses": NODE, "with": {"node-version": "24"}}, {"uses": UV, "with": {"version": "0.9.26"}},
                  run("Install Linux harness keyring build prerequisites", """sudo apt-get update
sudo apt-get install --yes --no-install-recommends pkg-config libdbus-1-dev
""", **{"if": "${{ needs.admission.outputs.profile == 'ejm-harness' && runner.os == 'Linux' }}"}),
                  run("Install pinned Rust tools", """if [[ "$PROFILE" == ejm-* ]]; then
  rustup toolchain install 1.99.1 --profile minimal --component clippy,rustfmt
  rustup default 1.99.1
  if [[ "$PROFILE" != ejm-ui ]]; then
    cargo install cargo-deny --version 0.20.2 --locked
    cargo install cargo-machete --version 0.9.2 --locked
  fi
fi
"""),
                  {"name": "Prepare ejm-cli remote test prerequisites", "if": "${{ needs.admission.outputs.profile == 'ejm-cli' }}", "uses": "./product/.github/actions/setup-ci"},
                  run("Run the project's required gate without secrets or write tokens", """cd product
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
    node scripts/size.mjs
    npm run size -w @ejm/demos
    npm run check:rust
    node scripts/pack-proof.mjs
    ;;
  ejmlabs) node scripts/check.mjs; npm --prefix site test; npm --prefix site run build ;;
  .github) python3 -m unittest discover -s tests -v; python3 scripts/build_workflows.py --check ;;
  *) exit 1 ;;
esac
""")],
    }
    registry = {
        "needs": ["admission", "prepare"], "if": "${{ github.run_attempt == 1 }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 25, "permissions": {},
        "env": {"CARGO_BUILD_JOBS": "2", "CARGO_INCREMENTAL": "0", "PROFILE": "${{ needs.admission.outputs.profile }}"},
        "steps": [ARTIFACT, EXTRACT, {"uses": NODE, "if": "${{ needs.admission.outputs.profile == 'ejm-harness' }}", "with": {"node-version": "24"}},
                  run("Run separate registry gate when applicable", """if [[ "$PROFILE" == ejm-harness ]]; then
  rustup toolchain install 1.99.1 --profile minimal --component clippy,rustfmt --target wasm32-unknown-unknown
  rustup default 1.99.1
  cargo install cargo-deny --version 0.20.2 --locked
  cargo install cargo-machete --version 0.9.2 --locked
  cargo install worker-build --version 0.8.7 --locked --jobs 2
  cd product
  if [[ -d ../ejm-ui ]]; then
    npm --prefix ../ejm-ui ci --ignore-scripts
  fi
  npm ci --ignore-scripts
  npm --prefix registry ci --ignore-scripts
  ./scripts/check-registry
fi
""")],
    }
    standards = {
        "needs": ["admission", "prepare"], "if": "${{ github.run_attempt == 1 }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 3, "permissions": {},
        "env": {"PROFILE": "${{ needs.admission.outputs.profile }}"},
        "steps": [ARTIFACT, EXTRACT, run("Validate shared public standards and version metadata", python(standards_check, 'product "$PROFILE"'))],
    }
    requirements = (ROOT / "review/reviewer-requirements.txt").read_text()
    install = 'cd "$RUNNER_TEMP"\n' + python("import os\nfrom pathlib import Path\nPath(os.environ['RUNNER_TEMP'], 'reviewer-requirements.txt').write_text(" + repr(requirements) + ")\n") + """set +e
{
  python3 -m venv "$RUNNER_TEMP/reviewer-venv" &&
  "$RUNNER_TEMP/reviewer-venv/bin/python" -m pip install --isolated --no-cache-dir --require-hashes --no-deps --only-binary=:all: -r "$RUNNER_TEMP/reviewer-requirements.txt"
} > "$RUNNER_TEMP/reviewer-install.log" 2>&1
reviewer_status=$?
set -e
if [ "$reviewer_status" -ne 0 ]; then
  printf 'reviewer install exit %s\\n' "$reviewer_status"
  exit "$reviewer_status"
fi
"""
    # The documented action runner reviews the admitted PR through the API; no PR code is checked out here.
    review = """printf '{"action":"opened","pull_request":{"url":"https://api.github.com/repos/%s/pulls/%s"}}' "$GITHUB_REPOSITORY" "$PR_NUMBER" > "$RUNNER_TEMP/review-event.json"
cd "$RUNNER_TEMP"
GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$RUNNER_TEMP/review-event.json" "$RUNNER_TEMP/reviewer-venv/bin/python" -I -m pr_agent.servers.github_action_runner
"""
    ai = {
        "needs": "admission", "if": "${{ github.run_attempt == 1 && needs.admission.outputs.run == 'true' }}", "runs-on": "ubuntu-24.04", "timeout-minutes": REVIEWER_JOB_TIMEOUT_MINUTES,
        "environment": "legacy-review",
        "permissions": {"contents": "read", "pull-requests": "write", "statuses": "read"}, "env": ENV,
        "steps": [REJECT_DEBUG, VERIFY,
                  run("Require the review model key", 'test "$HAS_MODEL_KEY" = true\n', env={"HAS_MODEL_KEY": "${{ secrets.XAI_API_KEY != '' }}"}),
                  run("Install the pinned reviewer", install, env={"GH_TOKEN": "", "GITHUB_TOKEN": "", "PIP_CONFIG_FILE": "/dev/null"}),
                  run("Automated review", review, env={
                      "GITHUB_TOKEN": "${{ github.token }}", "XAI__KEY": "${{ secrets.XAI_API_KEY }}",
                      "CONFIG__MODEL": REVIEWER_MODEL, "CONFIG__FALLBACK_MODELS": REVIEWER_FALLBACK_MODELS,
                      "CONFIG__REASONING_EFFORT": REVIEWER_REASONING_EFFORT, "CONFIG__AI_TIMEOUT": str(REVIEWER_AI_TIMEOUT),
                      "CONFIG__LOG_LEVEL": "INFO",
                      "CONFIG__USE_REPO_SETTINGS_FILE": "false", "CONFIG__USE_GLOBAL_SETTINGS_FILE": "false",
                      "GITHUB_ACTION_CONFIG__AUTO_REVIEW": "true", "GITHUB_ACTION_CONFIG__AUTO_DESCRIBE": "false",
                      "GITHUB_ACTION_CONFIG__AUTO_IMPROVE": "false",
                      "PR_REVIEWER__ENABLE_REVIEW_LABELS_SECURITY": "true", "PR_REVIEWER__ENABLE_REVIEW_LABELS_EFFORT": "true",
                      "PR_REVIEWER__REQUIRE_MERGE_RECOMMENDATION": "true"}),
                  VERIFY],
    }
    labels = {"needs": ["admission", "ai"], "if": "${{ github.run_attempt == 1 && needs.admission.outputs.run == 'true' }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 3,
              "permissions": {"pull-requests": "read"}, "env": {"PR_NUMBER": "${{ needs.admission.outputs.pr }}", "GH_TOKEN": "${{ github.token }}"},
              "steps": [run("Fail on blocking review labels", python(source("governance.py"), "labels"))]}
    # Removing a review label is the logged maintainer override; re-evaluate only a completed, label-blocked review.
    override = {"if": "${{ github.run_attempt == 1 && github.event_name == 'pull_request_target' && github.event.action == 'unlabeled' }}",
                "runs-on": "ubuntu-24.04", "timeout-minutes": 3,
                "permissions": {"contents": "read", "pull-requests": "read", "statuses": "write"},
                "concurrency": {"group": "human-command-${{ github.repository }}-${{ github.event.pull_request.number }}", "cancel-in-progress": False},
                "steps": [run("Re-evaluate the review after a label removal", python(source("governance.py"), "relabel"), env={"GH_TOKEN": "${{ github.token }}"})]}
    finish = {"needs": ["admission", "prepare", "quality", "registry", "standards", "ai", "labels"],
              "if": "${{ github.run_attempt == 1 && always() && needs.admission.outputs.run == 'true' }}", "runs-on": "ubuntu-24.04", "timeout-minutes": 3,
              "permissions": {"contents": "read", "pull-requests": "write", "statuses": "write"},
              "env": {**ENV, "JOB_RESULTS": "${{ toJSON(needs) }}"},
              "steps": [run("Publish required results only after live admission validation", python(source("governance.py"), "finish"))]}
    return {"name": "Human-admitted PR checks", "on": {"workflow_call": {"secrets": {"XAI_API_KEY": {"required": False}, "EJM_HARNESS_TOKEN": {"required": False}}}}, "permissions": {}, "jobs": {"admission": admission, "prepare": prepare, "quality": quality, "registry": registry, "standards": standards, "ai": ai, "labels": labels, "finish": finish, "override": override}}


def release_workflow():
    inputs = {"commit": {"required": True, "type": "string"}, "version": {"required": True, "type": "string"}, "standards-ref": {"required": True, "type": "string"}}
    # Embed libraries, not their command entry points, before the release entry point.
    code = source("governance.py", True) + "\n" + source("standards.py", True) + "\n" + source("prepare.py", True) + "\n" + source("release.py")
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


def main():
    for name, data in (("governance.yml", governance()), ("draft-release.yml", release_workflow())):
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
