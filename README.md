# 🏈 FantasyFootballCrew

> A highly customizable fantasy football platform: custom scoring, multiple league formats, coaches & coordinators, and AI-powered analysis.

**Live:** [fantasyfootballcrew.com](https://fantasyfootballcrew.com)

## Tech stack

| Component | Technology |
|-----------|-----------|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4 |
| Backend | FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2 |
| Database | SQLite (local dev) / PostgreSQL (production, Railway) |
| Auth | Email/password with JWT (bcrypt), email verification, password reset |
| NFL data | Sleeper API (players, stats, projections), ESPN scoreboard (live game status) |
| AI | OpenAI or Anthropic API (optional, stub mode without a key) |
| Email / monitoring | Resend (optional), Sentry (optional) |
| Hosting | Vercel (frontend) + Railway (backend); see [DEPLOYMENT.md](DEPLOYMENT.md) |

**Requirements:** Node.js 22+, Python 3.12+.

## Quick start

### Backend

```bash
cd backend
python -m venv venv
# macOS/Linux:
source venv/bin/activate
# Windows (PowerShell):  venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
alembic upgrade head            # create/upgrade the local SQLite schema
python -m uvicorn app.main:app --port 8001 --reload
```

API docs: http://localhost:8001/docs

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. The frontend talks to `http://localhost:8001` by default (override with `NEXT_PUBLIC_API_URL`).

### Both at once

```bash
cd frontend
npm run dev:all
```

`dev:all` starts the API through `scripts/dev-api.mjs`, which works on any OS. It uses `backend/venv` or `backend/.venv` if one exists and otherwise falls back to `python3`/`python` on your PATH. Set `API_PORT` to change the port (default 8001).

## Tests & checks

```bash
cd backend && python -m pytest -q      # backend test suite (isolated in-memory SQLite)
cd frontend && npm run lint            # ESLint (CI fails on errors)
cd frontend && npm run build           # production build + typecheck
```

CI (`.github/workflows/ci.yml`) runs all three on every push and PR to `master`.

## Project structure

```
fantasyfootballcrew/
├── frontend/              # Next.js app
│   ├── src/app/           # Routes (dashboard, leagues, draft, players, ai-analysis, admin, ...)
│   ├── src/components/    # Shared UI components
│   ├── src/lib/           # API client, hooks, utils
│   └── scripts/           # Dev tooling (dev-api.mjs)
├── backend/
│   ├── app/api/v1/        # REST endpoints
│   ├── app/models/        # SQLAlchemy ORM models
│   ├── app/schemas/       # Pydantic schemas
│   ├── app/services/      # Business logic (scoring, Sleeper sync, drafts, waivers, AI, ...)
│   ├── app/core/          # Config, DB, rate limiting, Sentry
│   ├── alembic/           # Database migrations
│   ├── scripts/           # Operational scripts (Sleeper sync, data backfills)
│   └── tests/             # pytest suite
└── DEPLOYMENT.md          # Vercel/Railway deployment guide
```

## Features

- **Customizable scoring:** any stat, any weight, any bonus, including IDP
- **League types:** standard, 2-Man Teams, Conference, Dual-Squad, Guillotine, Best Ball
- **Salary cap & contracts, playoffs, waivers, trades, commissioner tools**
- **Live drafts:** real-time draft room, pick queue, timers, CPU auto-draft, mock drafts
- **Coaches & Coordinators:** HC, OC, DC, STC with performance bonuses
- **AI analysis:** lineup, trade, bet, team and player comparison, AI commissioner digests
- **Live scoring:** current NFL week tracking, live/final game status
