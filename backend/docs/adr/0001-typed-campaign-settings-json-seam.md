# Typed campaign settings at the JSON seam

Campaign settings are immutable, strict Pydantic models in application memory, while
`Campaign.settings` and the settings snapshot inside `Turn.check_data` remain JSON dictionaries.
Explicit serialization on write and validation on read provide typed callers without migrating
existing JSONB rows or changing HTTP and SSE payloads.
