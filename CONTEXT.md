# Cairn context

The backend lives in `backend/`. It is an AI Dungeon Master platform: routes are HTTP-only,
domain modules own rules, query modules own persistence, and `llm/client.py` is the only LLM
call seam. Preserve HTTP, SSE, JSONB, prompt, and gameplay contracts during architecture work.

Architecture work proceeds one reviewed slice at a time. The current completed seam is typed
campaign settings; its JSONB representation remains a dictionary at persistence boundaries.
