"""Step-by-step import test."""
import sys
sys.path.insert(0, 'D:\\fantasyfootballcrew\\backend')
print("1. testing config import...")
from app.core.config import settings
print(f"   DB URL: {settings.DATABASE_URL}")
print("2. testing database import...")
from app.core.database import Base, engine, async_session
print("   database import OK")
print("3. testing model imports...")
from app.models.team import Team
from app.models.league import League
from app.models.user import User
print("   all model imports OK")
print("ALL IMPORTS SUCCESSFUL")
