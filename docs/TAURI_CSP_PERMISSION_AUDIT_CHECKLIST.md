# Tauri CSP + Permission Audit Checklist

Use this checklist before declaring Phase C security gates complete.

## Tauri permission surface

- [ ] Enumerate all invoked Tauri commands and confirm each is required for production.
- [ ] Ensure no debug-only commands are exposed in production build.
- [ ] Verify command argument validation for:
  - safe mode values,
  - screen source values,
  - proposal/action identifiers.
- [ ] Confirm file path handling uses expected allowlist and no unconstrained path traversal.

## CSP hardening

- [ ] Confirm production CSP excludes development hosts/origins.
- [ ] Confirm no wildcard `*` for script/style/connect in production.
- [ ] Confirm websocket/connect-src is limited to intended backend endpoint(s).
- [ ] Confirm local file/image source rules are minimized to required scopes.

## Runtime validation

- [ ] Build production frontend bundle and launch desktop shell with production config.
- [ ] Run smoke checks:
  - chat send/receive,
  - tool execution telemetry,
  - interrupt/approval path,
  - audit export + verify.
- [ ] Capture security sign-off note with timestamp + reviewer.

## Evidence artifacts

- [ ] `tauri.conf.json` review snapshot
- [ ] CSP effective value capture
- [ ] command inventory + approval record
- [ ] smoke test log reference
