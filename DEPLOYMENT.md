# FantasyFootballCrew — Deployment Guide

## Overview

- **Frontend:** Vercel (Next.js 16)
- **Backend:** Railway (FastAPI + PostgreSQL)
- **Domain:** fantasyfootballcrew.com (Namecheap)

---

## Backend — Railway

### Prerequisites

1. [Railway account](https://railway.app) — free tier works
2. [Railway CLI](https://docs.railway.app/develop/cli) (optional)

### Steps

```bash
# 1. Navigate to backend
cd fantasyfootballcrew/backend

# 2. Deploy via Railway CLI
railway login
railway init
railway up

# Or link existing project:
railway link <project-id>
railway up
```

### Environment Variables (Railway Dashboard)

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Railway auto-provides PostgreSQL URL |
| `JWT_SECRET` | `<random-string>` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `CORS_ORIGINS` | `["https://fantasyfootballcrew.com","https://www.fantasyfootballcrew.com"]` | JSON array of allowed origins |
| `ENVIRONMENT` | `production` | Tags Sentry events; defaults to `development` if unset |
| `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` | `<key>` | Optional. Powers real AI Analysis; without either, the feature runs in a fallback/stub mode |
| `RESEND_API_KEY` | `<key>` | Optional. Powers real password-reset emails; without it, reset links are logged server-side instead (`railway logs`) — still fully functional, just needs manual delivery |
| `RESEND_FROM_EMAIL` | `FantasyFootballCrew <onboarding@resend.dev>` | Optional override; the default needs no domain verification |
| `FRONTEND_URL` | `https://fantasyfootballcrew.com` | Used to build the link inside password-reset emails; defaults to this already |
| `SENTRY_DSN` | `<dsn>` | Optional. Turns on backend error monitoring; without it, `sentry_sdk` is never initialized (true no-op) |

### Railway Auto-Configuration

The project includes:
- `Procfile` — `web: alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `railway.json` — same startCommand (this is the one Railway actually uses; Procfile is kept in sync for anyone reading it, but railway.json wins when both exist), health check, restart policy
- `requirements.txt` — all dependencies incl. `asyncpg` for PostgreSQL and `alembic` for migrations

### Database Migrations (Alembic)

Schema changes are Alembic migrations now, not hand-rolled scripts.
`alembic upgrade head` runs automatically as part of every deploy's start
command (see above), before the server starts accepting traffic — so a
normal deploy with a schema change is just "commit the migration, push."

**Making a schema change:**

```bash
cd backend
source venv/Scripts/activate   # or venv/bin/activate on macOS/Linux

# 1. Edit the model(s) in app/models/
# 2. Autogenerate a migration from the diff against your local DB:
alembic revision --autogenerate -m "add whatever_column to whatever_table"

# 3. Read the generated file in alembic/versions/ before trusting it --
#    autogenerate is a diffing tool, not a guarantee. It won't detect
#    column renames (sees a drop + an add), doesn't know your intent for
#    backfilling a new NOT NULL column on a table with existing rows, and
#    can bake in a dialect-specific server_default if you generate it
#    while pointed at the "wrong" database for what you're testing against
#    -- see the baseline migration's own docstring for a real example of
#    that last one (sa.func.now(), not a raw sa.text(...) literal, for
#    anything that needs to work on both SQLite and Postgres).

# 4. Apply it locally and confirm it does what you expect:
alembic upgrade head

# 5. Commit the migration file, push. Railway runs it automatically.
```

**Checking where a database stands:**

```bash
alembic current           # what revision is this DB stamped at
alembic check              # "No new upgrade operations detected" == DB matches models exactly
alembic history             # full migration lineage
```

**Local dev DB (SQLite) vs. production (Postgres):** `DATABASE_URL` is
read the same way the app itself reads it (`alembic/env.py` imports
`settings` directly), so just export `DATABASE_URL` before an Alembic
command to target a specific database — same pattern as the old
`migrate_add_*.py` scripts.

**History:** this project ran without Alembic for a while — schema
changes shipped as hand-rolled `migrate_add_*.py` scripts (idempotent,
check-then-`ALTER TABLE`, run manually against production before the
code that depended on them). Those scripts are left in `backend/` as a
historical record of how the schema got to where it is; the first real
Alembic migration (`alembic/versions/..._baseline_schema_as_of_alembic_adoption.py`)
is a from-scratch snapshot of that already-evolved schema, and both the
local dev DB and production were `alembic stamp head`-ed at it (marks a
DB as already being at that revision without running any DDL) rather
than having it actually re-run against data that already matched.
Don't add new `migrate_add_*.py` scripts — write an Alembic migration
instead.

---

## Frontend — Vercel

### Prerequisites

1. [Vercel account](https://vercel.com)
2. [Vercel CLI](https://vercel.com/docs/cli) (optional)

### Steps

```bash
# 1. Navigate to frontend
cd fantasyfootballcrew/frontend

# 2. Deploy via Vercel CLI (or connect GitHub repo)
vercel login
vercel --prod

# 3. Set env vars
vercel env add NEXT_PUBLIC_API_URL
```

### Environment Variables (Vercel Dashboard)

| Variable | Value | Notes |
|----------|-------|-------|
| `NEXT_PUBLIC_API_URL` | `https://<railway-app>.up.railway.app` | Your Railway backend URL |
| `NEXT_PUBLIC_SENTRY_DSN` | `<dsn>` | Optional. Turns on frontend error monitoring (client + server + edge); without it, a documented no-op. Sentry DSNs are meant to be public (write-only), safe in a `NEXT_PUBLIC_` var |

To upload real source maps to Sentry (readable stack traces instead of
minified code) also add `SENTRY_ORG`, `SENTRY_PROJECT`, and
`SENTRY_AUTH_TOKEN` — see `next.config.ts`. Without them the build just
skips source map upload; error capture itself isn't affected.

### Vercel Configuration

The project includes `vercel.json` with:
- Build: `npm run build`
- Output: `.next`
- Framework: Next.js

---

## Domain Setup

### DNS (Namecheap → Vercel)

1. In Vercel dashboard, add domain `fantasyfootballcrew.com`
2. In Namecheap, set custom DNS to Vercel's nameservers:
   - `dns1.vercel-dns.com`
   - `dns2.vercel-dns.com`
3. Wait for propagation (5–30 minutes)

### DNS (Namecheap → Railway)

Railway provides a `*.up.railway.app` URL. For a custom domain:
1. In Railway dashboard, add custom domain for the backend service
2. Add a CNAME record in Namecheap pointing to the Railway URL

---

## Post-Deployment Checklist

- [ ] Backend health check: `GET https://api.fantasyfootballcrew.com/health`
- [ ] Frontend loads: `https://fantasyfootballcrew.com`
- [ ] Registration flow works
- [ ] Create league works
- [ ] Draft board loads
- [ ] Scoring settings save/load
- [ ] Standings display
- [ ] Sleeper player sync (run manually via Railway console)
- [ ] SSL certificates (auto by Vercel/Railway)

### Manual Sleeper Sync (after deploy)

```bash
# Via Railway CLI or console:
cd backend
python -c "
import asyncio
from app.core.database import async_session, engine
from app.services.sleeper_sync import sync_players_to_db

async def sync():
    async with async_session() as db:
        count = await sync_players_to_db(db)
        print(f'Synced {count} players')
    await engine.dispose()

asyncio.run(sync())
"
```

---

## Local Development

```bash
# Backend
cd backend
source venv/Scripts/activate
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

# Frontend
cd frontend
npm run dev

# Or start both together (from frontend/):
npm run dev:all
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8001
- API Docs: http://localhost:8001/docs

Note: `next.config.ts` proxies `/api/*` to `http://localhost:8001` in dev, and
several frontend files fall back to that same port when `NEXT_PUBLIC_API_URL`
isn't set. Running the backend on any other port will silently break local
API calls (they fail quietly — the pages catch errors and show empty states
rather than surfacing a fetch failure).

---

## Architecture Notes

### API Routes (48 total)

| Group | Endpoints | Purpose |
|-------|-----------|---------|
| Auth | `/api/v1/auth/*` | Register, login, JWT |
| Leagues | `/api/v1/leagues/*` | CRUD, scoring config, commissioner |
| Teams | `/api/v1/teams/*` | CRUD, bulk-add CPU, claim |
| Players | `/api/v1/players/*` | NFL player list/search |
| Draft | `/api/v1/drafts/*` | Snake draft, timer, auto-pick, mock |
| Scoring | `/api/v1/scoring/*` | Calculator, validation, Sleeper weekly |
| Standings | `/api/v1/leagues/{id}/standings/*` | Standings, weekly scores, calculate |
| Commissioner | `/api/v1/leagues/{id}/commissioner/*` | Adjustments, trades, draft order |
| AI | `/api/v1/ai/*` | Analysis, lineup, trade (needs API key) |

### Frontend Pages

| Route | Page |
|-------|------|
| `/` | Landing page |
| `/login` | Log in |
| `/register` | Sign up |
| `/dashboard` | League list |
| `/leagues/create` | Create league |
| `/leagues/[id]` | League detail + team mgmt |
| `/leagues/[id]/scoring` | Scoring settings |
| `/leagues/[id]/standings` | Standings + weekly scores |
| `/leagues/[id]/commissioner` | Commissioner panel |
| `/draft/[id]` | Draft war room |

### Key Features Status

| Feature | Status |
|---------|--------|
| ✅ Landing page | Complete |
| ✅ Auth (JWT) | Complete |
| ✅ League CRUD | Complete |
| ✅ Team management | Complete |
| ✅ Snake draft w/ timer | Complete |
| ✅ Auto-pick (CPU) | Complete |
| ✅ Mock drafts | Complete |
| ✅ Scoring settings UI | Complete |
| ✅ Scoring engine | Complete |
| ✅ Standings + weekly | Complete |
| ✅ Commissioner controls | Complete |
| ✅ Player sync (Sleeper) | Complete |
| ✅ Bulk CPU team add | Complete |
| ✅ Waivers (claims, priority, commissioner process) | Complete |
| ✅ Trades (propose, history, commissioner approve/deny) | Complete |
| ✅ Coach/Coordinator UI | Complete (commissioner panel) |
| 🔲 AI Chat (The Oracle) | Wired to OpenAI/Anthropic, needs API key set in env |