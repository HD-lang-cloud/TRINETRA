import os
import sys
from pathlib import Path

# Ensure project root and backend directory are on sys.path
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
for p in [str(ROOT_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from init_db import initialize_database
from utils.data_seeder import seed_demo_dataset
from database import resolve_db_path

# Create Flask application instance
app = create_app("production")

# Auto-initialize and seed database on fresh cloud deploy
with app.app_context():
    db_file = resolve_db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if not db_file.exists() or db_file.stat().st_size == 0:
        app.logger.info("Fresh deploy detected — initializing schema and seeding demo data...")
        initialize_database(str(db_file))
        seed_demo_dataset(str(db_file))
        app.logger.info("Database ready.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
