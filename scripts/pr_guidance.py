#!/usr/bin/env python3
"""Render advisory next steps from live PR metadata, without granting admission."""
import json
import os
import re
from pathlib import Path

from governance import GitHub

START = '<!-- ejm-next-action:start -->'
END = '<!-- ejm-next-action:end -->'
CHECKS = ('Quality', 'Repository standards', 'AI review')


def render(pr, statuses):
    sha = pr['head']['sha']
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Invalid PR head')
    command = lambda name: f'```text\n/{name} {sha}\n```'
    ready = statuses.get('Human readiness', {}).get('state')
    approval = statuses.get('Maintainer approval', {}).get('state')
    if pr['state'] != 'open':
        text = 'This PR is merged.' if pr.get('merged') else 'This PR is closed.'
    elif pr.get('draft'):
        text = 'Finish the draft and mark this PR ready for review before admission.'
    elif pr['base']['ref'] != 'main':
        text = 'Merge the predecessor, then retarget this PR to main before admission.'
    elif (pr['head'].get('repo') or {}).get('full_name') != (pr['base'].get('repo') or {}).get('full_name'):
        text = 'Fork PRs require manual review instead of automated admission.'
    elif ready != 'success':
        text = 'A human maintainer must post this as a **new PR comment** to start checks:\n\n' + command('ready')
    elif any(statuses.get(key, {}).get('state') in ('failure', 'error') for key in CHECKS):
        text = ('Checks failed. Fix the reported causes before requesting another run. '
                'A new commit needs a fresh `/ready` command for its new SHA. '
                'To retry this unchanged commit, first post:\n\n' + command('revoke') +
                '\n\nThen post a separate new comment:\n\n' + command('ready'))
    elif not all(statuses.get(key, {}).get('state') == 'success' for key in CHECKS):
        text = 'Required checks are running or missing. Wait for their results before approval.'
    elif approval != 'success':
        text = 'Checks passed. After reviewing this exact commit, a human maintainer must post:\n\n' + command('approve')
    else:
        text = 'Checks and maintainer approval passed. Merge through the protected PR flow; GitHub remains authoritative for any remaining restrictions.'
    return (START + '\n## Next action\n\n' + text + '\n\n'
            f'Current head: `{sha}`. This section is generated guidance, not approval. '
            'A command in the PR description does not execute it.\n' + END)


def update_body(body, section):
    body = body or ''
    starts, ends = body.count(START), body.count(END)
    if starts == ends == 0:
        result = section + '\n\n' + body
    elif starts == ends == 1 and body.index(START) < body.index(END):
        start, end = body.index(START), body.index(END) + len(END)
        result = body[:start] + section + body[end:]
    else:
        raise ValueError('Ambiguous generated guidance markers; preserve body and repair markers')
    if len(result.encode('utf-8')) > 60000:
        raise ValueError('PR description is too large to add guidance safely')
    return result


def refresh(api, number):
    # All event types use live metadata, never an event's possibly stale head/body.
    for _ in range(3):
        pr = api.request(f'/pulls/{int(number)}')
        body = update_body(pr.get('body'), render(pr, api.statuses(pr['head']['sha'])))
        if body == (pr.get('body') or ''):
            return
        latest = api.request(f'/pulls/{int(number)}')
        if any(latest.get(key) != pr.get(key) for key in ('head', 'base', 'body', 'state', 'draft', 'merged')):
            continue
        api.request(f'/pulls/{int(number)}', 'PATCH', {'body': body})
        return
    raise ValueError('PR changed during guidance update; retry on its next event')


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    if os.environ['GITHUB_EVENT_NAME'] == 'pull_request_target':
        number = event['number']
    elif os.environ['GITHUB_EVENT_NAME'] == 'issue_comment' and event['issue'].get('pull_request'):
        number = event['issue']['number']
    else:
        raise ValueError('Unsupported guidance event')
    refresh(GitHub(), number)


if __name__ == '__main__':
    main()
