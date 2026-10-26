## 1. Script and workflows

- [x] 1.1 Add `scripts/attach.py` with run, tag, draft and digest checks.
- [x] 1.2 Generate `verify-build.yml` and `attach-assets.yml`; allow them in the standards check and repository configuration.

## 2. Verification

- [x] 2.1 Tests refuse a changed digest, an extra or missing file, a wrong-SHA run, a wrong workflow or trigger, a wrong tag, and a non-draft release.
- [x] 2.2 `python3 -m unittest discover -s tests` and `python3 scripts/build_workflows.py --check` pass.
