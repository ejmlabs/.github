# Human gate acceptance fixture

This branch is a controlled test fixture. Keep its PR unmerged.

Apply `acceptance:missing-model-key` before admitting this exact head. The
shared caller then forwards no model key. Separate human readiness and
approval should allow Quality and Repository standards to finish, while both
AI jobs fail at the missing-key guard before Codex executes. Keep all merge
protections enforced and verify that AI review is the only failed requirement.

A later fixture commit adds a bounded wait in the secret-free Quality job.
After confirming native approval and that the wait is active, a human may
revoke that exact head. Verify both human statuses fail, native approval is
dismissed, the active admitted run is cancelled, and finalization does not
restore successful human statuses. Neither fixture should call a model.

Retain the run, job, comment, status, review, and source-revision evidence.
Close the PR and remove its fixture label when the checks are complete.
