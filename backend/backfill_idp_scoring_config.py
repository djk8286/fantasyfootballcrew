"""
Backfill: add the new "idp" scoring category to existing leagues'
scoring_config.

DEFAULT_SCORING gaining an "idp" category only affects leagues CREATED
after this change (create_league seeds scoring_config from a deep copy of
DEFAULT_SCORING at creation time) -- every league created before it has
its own already-persisted scoring_config JSON blob with no "idp" key at
all, so individual defensive players would still silently score 0 for
them even after this deploy.

This is a DATA backfill, not a schema migration (scoring_config already
exists as a column -- see migrate_*.py for actual ALTER TABLE scripts).
Purely additive: only touches leagues missing the "idp" key entirely,
and only adds that one key -- never overwrites anything a league already
explicitly configured for any other category. Safe to run repeatedly
(no-ops on leagues that already have it). Works against whatever
DATABASE_URL is configured -- SQLite locally, Postgres in production.

Run once after deploying: `python backfill_idp_scoring_config.py`
"""
import asyncio
from sqlalchemy import select
from app.core.database import async_session
from app.models.league import League
from app.services.scoring_engine import DEFAULT_SCORING


async def backfill():
    idp_defaults = dict(DEFAULT_SCORING["idp"])
    async with async_session() as db:
        result = await db.execute(select(League))
        leagues = result.scalars().all()

        updated = 0
        for league in leagues:
            config = league.scoring_config
            if config is None:
                league.scoring_config = {"idp": dict(idp_defaults)}
                updated += 1
            elif "idp" not in config:
                config["idp"] = dict(idp_defaults)  # MutableDict -- this assignment IS tracked
                updated += 1

        await db.commit()
        print(f"Checked {len(leagues)} league(s), added 'idp' scoring to {updated}.")


if __name__ == "__main__":
    asyncio.run(backfill())
