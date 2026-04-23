# Audit Verify Report Schema

This document defines the machine-readable verification report emitted by the in-app audit verifier.

## Schema ID

- `schema_version`: `owlynn.audit.verify-report.v1`

## Required fields

- `schema_version` (string): schema identifier/version.
- `ts` (number): unix epoch milliseconds when verification result was recorded.
- `status` (`pass` | `fail`): overall verification outcome.
- `reason` (string): short human-readable result reason.
- `records_checked` (number): number of JSONL records processed up to completion/failure.

## Optional fields

- `root_hash` (string): final/root chain hash when available.
- `manifest_file` (string): manifest filename used for verification.
- `bundle_file` (string): JSONL bundle filename used for verification.
- `trace` (string[]): ordered step/failure trace markers for forensic triage.

## Semantics

- `status=pass`
  - `reason` should indicate successful verification.
  - `records_checked` should equal total parsed record count.
  - `root_hash` should be present.
- `status=fail`
  - `reason` should indicate failing stage (e.g., hash chain/root/digest/signature mismatch).
  - `records_checked` should indicate progress up to failure point.
  - `trace` should include failure context snippets where possible.

## Compatibility notes

- Consumers should ignore unknown fields for forward compatibility.
- Producers should preserve existing field meanings for v1.
