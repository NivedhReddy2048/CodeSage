# CodeSage

Multi-agent code review for GitHub pull requests. Every PR is reviewed by a
six-agent LangGraph pipeline grounded in the repository's own code through hybrid
retrieval (pgvector dense + Postgres full-text), so findings carry real file and
line citations rather than generic advice.

Architecture, tech-stack rationale and free-tier constraints: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md).
Build status: [docs/PROGRESS.md](docs/PROGRESS.md).

> Scaffold stage (phase 0). The full README — architecture diagram, deployment
> guide and engineering-tradeoffs section — is written in phase 7.

## Layout

```
backend/    Django + DRF + Channels (ASGI via Daphne), eight apps under backend/apps/
frontend/   Next.js + TypeScript + Tailwind + shadcn/ui
docker/     Local-dev container support files
docs/       Specification, build prompts, progress
```

## Local development

Requires Docker Desktop, Python 3.13+ and Node 20+.

**1. Start Postgres (with pgvector) and Redis:**

```bash
docker compose up -d
```

**2. Backend:**

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows; use source .venv/bin/activate elsewhere
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Serves on http://localhost:8000 — health check at `/api/health/`, Swagger at `/api/docs/`.

**3. Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Serves on http://localhost:3000.

## Checks

```bash
cd backend  && ruff check . && python manage.py check && pytest
cd frontend && npm run lint && npm run build
```
