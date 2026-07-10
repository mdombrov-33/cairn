# ADR 0001: Typed campaign settings at the JSON seam

## Decision

Campaign settings are immutable, strict Pydantic models in application memory. `Campaign.settings`
and `Turn.check_data.settings` remain JSON dictionaries, produced with explicit `as_json()` calls
when written and validated back into `ResolvedCampaignSettings` when a paused turn resumes.

## Consequences

Callers use typed attributes and share one resolved turn snapshot. Existing JSONB rows, HTTP
responses, and SSE payloads keep their current shape; no migration or client change is required.
