---
name: add-provider
description: Add a new alert source (Datadog, Sentry, ...) to the ingestion pipeline. Use when asked to support a new alert provider/source.
---

# Add an alert provider

The engine never sees raw payloads — only `NormalizedAlert`. A new source is
one module + one registry line. Do NOT touch the correlation engine/worker.

## Steps (TDD: test first)

1. Test in `backend/tests/correlation/test_providers.py`: paste a real sample
   webhook payload, assert `parse()` output (source/name/severity/status/labels/
   annotations/starts_at). Severity must map into {critical, warning, info},
   default "info". Follow the Alertmanager tests as template.
2. `backend/app/providers/<name>.py`:
   ```python
   class DatadogProvider:
       name = "datadog"
       def parse(self, payload: dict) -> list[NormalizedAlert]: ...
   ```
   Keep identity attrs (host/service/cluster) in `labels` — grouping depends on them.
3. Register in `backend/app/providers/registry.py` `_PROVIDERS` dict. That's it:
   `POST /api/v1/ingest/datadog` now works (auth, persistence, 202, enqueue are generic).
4. Run backend-check skill. Add the provider name to docs if user-facing.

## Gotchas

- `parse()` must never raise on partial payloads — skip bad entries, return what's valid.
- Timestamps: convert to aware UTC datetimes (`fromisoformat` + Z replacement pattern).
- Fingerprint identity = source+name+labels, so keep label extraction stable across versions.
