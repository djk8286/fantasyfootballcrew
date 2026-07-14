"""Test that the FastAPI app imports properly."""
import sys
sys.path.insert(0, 'D:\\fantasyfootballcrew\\backend')
from app.main import app
print("App import OK")
print("Routes:")
for route in app.routes:
    if hasattr(route, 'methods') and hasattr(route, 'path'):
        print(f"  {route.methods} {route.path}")
    elif hasattr(route, 'path'):
        print(f"  {route.path}")
