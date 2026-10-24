import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pr_guidance as guidance
import build_workflows
import standards

SHA = 'a' * 40


def workflow_jobs(text):
    """Read job mappings and permissions from the generated YAML subset."""
    jobs = {}
    in_jobs, in_permissions = False, False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        if indent > 6:
            continue
        key, _, value = line.strip().partition(':')
        key = json.loads(key) if key.startswith('"') else key
        value = value.strip()
        if indent == 0:
            in_jobs = key == 'jobs'
        elif in_jobs and indent == 2:
            job = jobs[key] = {}
            in_permissions = False
        elif in_jobs and indent == 4:
            in_permissions = key == 'permissions'
            if key in ('permissions', 'uses'):
                job[key] = json.loads(value) if value.startswith(('"', '{')) else value or {}
        elif in_jobs and indent == 6 and in_permissions:
            job['permissions'][key] = json.loads(value) if value.startswith('"') else value
    return jobs


def pr():
    return {'head': {'sha': SHA}, 'base': {'ref': 'main'}, 'body': 'Author text',
            'state': 'open', 'draft': False, 'merged': False}


class GuidanceTests(unittest.TestCase):
    def test_next_action_tracks_admission_checks_and_approval(self):
        item = pr()
        states = {}
        self.assertIn('/ready ' + SHA, guidance.render(item, states))
        states['Human readiness'] = {'state': 'success'}
        self.assertNotIn('/approve', guidance.render(item, states))
        for check in guidance.CHECKS:
            states[check] = {'state': 'success'}
        self.assertIn('/approve ' + SHA, guidance.render(item, states))
        states['Maintainer approval'] = {'state': 'success'}
        self.assertIn('protected PR flow', guidance.render(item, states))
        states['Quality'] = {'state': 'failure'}
        self.assertIn('/revoke ' + SHA, guidance.render(item, states))
        self.assertNotIn('/approve', guidance.render(item, states))

    def test_draft_stack_and_closed_do_not_invite_admission(self):
        for changed in ({'draft': True}, {'base': {'ref': 'feature'}}, {'state': 'closed'}):
            self.assertNotIn('/ready', guidance.render({**pr(), **changed}, {}))

    def test_update_preserves_author_text_and_replaces_stale_sha(self):
        old = guidance.update_body('Description\n\n## Review\nKeep this.', guidance.render(pr(), {}))
        new = guidance.render({**pr(), 'head': {'sha': 'b' * 40}}, {})
        updated = guidance.update_body(old, new)
        self.assertNotIn(SHA, updated)
        self.assertTrue(updated.endswith('Description\n\n## Review\nKeep this.'))
        self.assertEqual(updated, guidance.update_body(updated, new))
        self.assertEqual(updated.count(guidance.START), 1)
        for bad in (guidance.START, guidance.END, guidance.END + guidance.START, old + guidance.START):
            with self.assertRaises(ValueError):
                guidance.update_body(bad, new)

    def test_live_refresh_retries_changed_head_and_is_idempotent(self):
        class API:
            def __init__(self):
                self.item, self.reads, self.writes = pr(), 0, []
            def request(self, path, method='GET', data=None):
                self.assert_path(path)
                if method == 'PATCH':
                    self.writes.append(data)
                    self.item['body'] = data['body']
                    return self.item
                self.reads += 1
                if self.reads == 2:
                    self.item['head']['sha'] = 'b' * 40
                    self.item['body'] += '\nConcurrent author edit'
                return copy.deepcopy(self.item)
            def assert_path(self, path):
                assert path == '/pulls/1'
            def statuses(self, sha):
                return {}
        api = API()
        guidance.refresh(api, 1)
        guidance.refresh(api, 1)
        self.assertEqual(len(api.writes), 1)
        self.assertIn('/ready ' + 'b' * 40, api.item['body'])
        self.assertTrue(api.item['body'].endswith('Concurrent author edit'))

    def test_guidance_never_receives_model_secrets_or_checks_out_pr_code(self):
        jobs = build_workflows.governance()['jobs']
        for name in ('guidance', 'guidance_finish'):
            job = jobs[name]
            self.assertEqual(job['permissions'], {'contents': 'read', 'pull-requests': 'write', 'statuses': 'read'})
            self.assertEqual(len(job['steps']), 1)
            self.assertNotIn('uses', job['steps'][0])
            self.assertEqual(job['steps'][0]['env'], {'GH_TOKEN': '${{ github.token }}'})
        self.assertIn("github.event_name == 'issue_comment'", jobs['admission']['if'])
        self.assertIn("needs.admission.outputs.run == 'true'", jobs['prepare']['if'])
        for name in ('quality', 'registry', 'standards', 'ai'):
            self.assertIn('prepare', jobs[name]['needs'])
            self.assertNotIn('always()', jobs[name]['if'])

    def test_pr_guidance_reusable_has_only_the_minimal_trusted_job(self):
        document = build_workflows.guidance_workflow()
        self.assertEqual(document['on'], {'workflow_call': {}})
        self.assertNotIn('secrets', document['on']['workflow_call'])
        self.assertEqual(document['permissions'], {})
        self.assertEqual(set(document['jobs']), {'guidance'})
        self.assertNotIn('"uses":', json.dumps(document))
        self.assertNotIn('secrets.', json.dumps(document))
        job = document['jobs']['guidance']
        self.assertEqual(job['permissions'], {'contents': 'read', 'pull-requests': 'write', 'statuses': 'read'})
        self.assertEqual(job['if'], "${{ github.run_attempt == 1 && github.event_name == 'pull_request_target' && github.event.sender.type != 'Bot' }}")
        self.assertEqual(job['timeout-minutes'], 2)
        self.assertNotIn('needs', job)
        for name in ('guidance', 'guidance_finish'):
            original = build_workflows.governance()['jobs'][name]
            self.assertEqual(job['steps'], original['steps'])
            self.assertEqual(job['concurrency'], original['concurrency'])

    def permission_violations(self, text):
        jobs = workflow_jobs(text)
        self.assertEqual(set(jobs), {'governance', 'guidance'})
        levels = {'none': 0, 'read': 1, 'write': 2}
        rendered = build_workflows.render_workflows()
        violations = []
        for caller_name, caller in jobs.items():
            target, revision = caller['uses'].split('@')
            self.assertEqual(revision, SHA)
            called = workflow_jobs(rendered[target.rsplit('/', 1)[1]])
            self.assertTrue(called)
            for name, job in called.items():
                for permission, requested in job.get('permissions', {}).items():
                    granted = caller.get('permissions', {}).get(permission, 'none')
                    if levels[requested] > levels[granted]:
                        violations.append((caller_name, name, permission, requested, granted))
        return violations

    def test_guided_callers_grant_every_permission_requested_by_their_reusables(self):
        self.assertEqual(self.permission_violations(standards.guided_consumer_workflows(SHA)['pr.yml']), [])

    def test_permission_check_detects_the_original_guidance_caller_bug(self):
        root = Path(__file__).resolve().parents[1]
        jobs = workflow_jobs((root / '.github/workflows/governance.yml').read_text())
        self.assertEqual(jobs['admission']['permissions']['statuses'], 'write')
        self.assertEqual(jobs['admission']['permissions']['actions'], 'write')
        self.assertEqual(jobs['finish']['permissions']['statuses'], 'write')
        caller = standards.guided_consumer_workflows(SHA)['pr.yml'].replace('/pr-guidance.yml@', '/governance.yml@')
        violations = self.permission_violations(caller)
        self.assertIn(('guidance', 'admission', 'statuses', 'write', 'read'), violations)
        self.assertIn(('guidance', 'admission', 'actions', 'write', 'none'), violations)

    def test_guided_caller_is_opt_in_and_pinned(self):
        old = standards.consumer_workflows(SHA)
        new = standards.guided_consumer_workflows(SHA)
        self.assertNotIn('pull_request_target', old['pr.yml'])
        self.assertNotIn('pr-guidance.yml', old['pr.yml'])
        self.assertIn('pull_request_target', new['pr.yml'])
        self.assertIn('governance.yml@' + SHA, new['pr.yml'])
        self.assertEqual(new['release.yml'], old['release.yml'])
        governance, guided = new['pr.yml'].split('\n  governance:\n', 1)[1].split('\n  guidance:\n', 1)
        self.assertIn("if: ${{ github.event_name == 'issue_comment' && github.event.issue.pull_request }}", governance)
        self.assertIn('    secrets:\n', governance)
        self.assertEqual(governance.replace("github.event_name == 'issue_comment' && ", '') + '\n', old['pr.yml'].split('  governance:\n', 1)[1])
        self.assertIn("if: ${{ github.event_name == 'pull_request_target' }}", guided)
        self.assertIn('pr-guidance.yml@' + SHA, guided)
        self.assertNotIn('secrets', guided)
        self.assertNotIn('actions:', guided)
        self.assertNotIn('statuses: write', guided)
        self.assertIn('    permissions:\n      contents: read\n      pull-requests: write\n      statuses: read\n', guided)

    def test_validator_accepts_only_the_secret_free_guided_shape(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            directory = root / '.github/workflows'
            directory.mkdir(parents=True)
            docs = standards.guided_consumer_workflows(SHA)
            for file, text in docs.items():
                (directory / file).write_text(text)
            standards.workflows(root, 'ejm-cli')
            leaked = docs['pr.yml'] + '    secrets:\n      XAI_API_KEY: ${{ secrets.XAI_API_KEY }}\n'
            widened = docs['pr.yml'].replace('      statuses: read\n', '      statuses: write\n      actions: write\n')
            old_target = docs['pr.yml'].replace('/pr-guidance.yml@', '/governance.yml@')
            different_pin = docs['pr.yml'].replace('pr-guidance.yml@' + SHA, 'pr-guidance.yml@' + 'b' * 40)
            mutable_pin = docs['pr.yml'].replace('pr-guidance.yml@' + SHA, 'pr-guidance.yml@main')
            for text in (leaked, widened, old_target, different_pin, mutable_pin):
                (directory / 'pr.yml').write_text(text)
                with self.assertRaises(ValueError):
                    standards.workflows(root, 'ejm-cli')

    def test_comment_guidance_is_limited_to_maintainers(self):
        condition = build_workflows.governance()['jobs']['guidance']['if']
        self.assertNotIn('pull_request_target', condition)
        comment = condition.split("github.event_name == 'issue_comment'", 1)[1]
        self.assertTrue(comment.startswith(" && contains(fromJSON('[\"OWNER\",\"MEMBER\",\"COLLABORATOR\"]'), github.event.comment.author_association) && "))
