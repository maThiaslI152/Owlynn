# Frontend Cutover Rollback Procedure

This procedure defines how to rollback a broken `frontend-v2` state to a known-good `frontend-v2` revision for personal local use.

## Trigger conditions

Execute rollback if any of the following occur in daily use:

- websocket chat unavailable or unstable across sessions,
- security approval flow fails (interrupts not rendered or decisions not delivered),
- audit export/verify path produces invalid artifacts,
- critical UI workflows (message send, project switch, tool execution visibility) are blocked.

## Rollback steps

1. Freeze rollout
   - stop current changes and freeze new edits until recovery is complete.
2. Restore known-good `frontend-v2` revision
   - reset local runtime to the last known-good frontend state (commit/tag/backup copy).
3. Restart application stack
   - restart backend and desktop shell processes with restored config/build.
4. Smoke-test minimum path
   - open app, send one message, verify websocket response,
   - verify security interrupt + approval loop,
   - verify no startup/runtime console fatal errors.
5. Communicate rollback status
   - annotate your local run log with rollback timestamp, trigger, and observed impact.

## Post-rollback checklist

- [ ] Capture failing `frontend-v2` logs/traces.
- [ ] Attach latest audit verify report artifact.
- [ ] Create remediation task list before re-attempting upgrade.
- [ ] Re-run Phase C reliability/security gates locally.

## Re-cutover prerequisites

- identified root cause fixed,
- focused regression test added,
- audit/verify flows pass,
- local smoke checks pass in your daily-use environment.
