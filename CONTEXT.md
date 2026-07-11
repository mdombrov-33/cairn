# Cairn context

The backend lives in `backend/`. It is an AI Dungeon Master platform: routes are HTTP-only,
domain modules own rules, query modules own persistence, and `llm/client.py` is the only LLM
call seam. Preserve HTTP, SSE, JSONB, prompt, and gameplay contracts during architecture work.

Architecture work proceeds one reviewed slice at a time. Completed seams are typed campaign
settings (whose JSONB representation remains a dictionary at persistence boundaries), turn
workflows (`pipelines/turn_graph.py` owns graph construction and routing while
`application/turns/` owns resolver persistence and agent coordination), and campaign/scene/NPC
workflows. The latter live in `application/`; their pure projections remain in `domain/services/`.
Character creation, equipment, progression, resources, and rest workflows also live in
`application/`; inventory, AC derivation, and feat effects remain pure domain rules.
