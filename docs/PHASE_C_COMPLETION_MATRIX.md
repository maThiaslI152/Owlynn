# Phase C Completion Matrix

Status reference for Phase C (Hardening + Cutover) checklist execution.

## Cutover

- [x] Dev startup defaults to `frontend-v2`.
  - Evidence: `start.sh`, `src-tauri/tauri.conf.json` (v2 dev/build targets).
- [x] Legacy `frontend/` runtime path retired from backend/static serving defaults.
  - Evidence: `src/api/server.py` now serves `frontend-v2/dist` only and legacy root endpoints are retired (`410`).

## Security

- [x] Tauri least-privilege permissions final pass.
  - Evidence: `docs/PHASE_C_SECURITY_SIGNOFF_2026-04-23.md` (conditional pass; human countersign recommended).
- [x] Production CSP hardening pass.
  - Evidence: `docs/PHASE_C_SECURITY_SIGNOFF_2026-04-23.md` (conditional pass; human countersign recommended).
- [x] Audit export + verify flow supports signed/unsigned integrity checks.
  - Evidence: `frontend-v2/src/components/ToolExecutionPanel.tsx`,
    `docs/AUDIT_EXPORT_VERIFY_RUNBOOK.md`.

## Reliability

- [x] Websocket contract regression checks in CI.
  - Evidence: `.github/workflows/ci.yml` (`audit-verify-gate`), `tests/test_websocket_event_contract.py`.
- [x] Verify fixture/schema regression checks.
  - Evidence: `tests/test_verify_report_fixture.py`, `docs/AUDIT_VERIFY_REPORT_SCHEMA.md`,
    `docs/examples/verify-report-sample.json`.
- [x] `frontend-v2` build gate in CI.
  - Evidence: `.github/workflows/ci.yml` (`npm ci && npm run build` in `audit-verify-gate`).
- [x] Frontend cutover serving contract checks.
  - Evidence: `tests/test_frontend_cutover_serving.py`, `.github/workflows/ci.yml`.

## Operations

- [x] Audit export/verify operator runbook.
  - Evidence: `docs/AUDIT_EXPORT_VERIFY_RUNBOOK.md`.
- [x] Rollback procedure documented.
  - Evidence: `docs/FRONTEND_CUTOVER_ROLLBACK.md`.
- [x] Rollback exercised and recorded with execution artifact.
  - Evidence: `docs/ROLLBACK_DRY_RUN_LOG.md`, `docs/PHASE_C_STAGING_REHEARSAL_RESULT_2026-04-23.md` (local personal-use rehearsal using known-good `frontend-v2` restore flow).
