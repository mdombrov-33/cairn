# Post-turn work remains supervised in-process

Lore extraction, scene post-processing, summarization, and companion reflection run through one
supervised in-process post-turn module. Central task tracking isolates failures and supports graceful
shutdown while preserving fire-and-forget request latency; a durable queue or outbox remains deferred
until deployment requirements justify its operational cost.
