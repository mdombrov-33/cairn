# Cairn

AI Dungeon Master platform for persistent TTRPG campaigns.

## Stack

- **Backend:** Python 3.14, FastAPI, SQLAlchemy 2, Alembic, pydantic
- **Agents:** LangGraph, MCP, LiteLLM, Tenacity
- **Data:** PostgreSQL, Qdrant (dev) / S3 Vectors (prod), Redis
- **Queues:** SQS + Taskiq (ElasticMQ locally), Lambda workers
- **LLM:** Bedrock / Anthropic / OpenAI via LiteLLM, Ollama for local, SageMaker for the fine-tuned DM voice model
- **Frontend:** Next.js, TypeScript, Tailwind, Clerk, Zustand, TanStack Query, SSE
- **Infra:** AWS (App Runner + Lambda + SageMaker + SQS + EventBridge), Terraform, GitHub Actions OIDC
- **Observability:** structlog, OpenTelemetry, Langfuse, Sentry
- **Dev:** uv, Docker (multi-stage), docker-compose, Makefile, pytest + testcontainers
