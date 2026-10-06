import os
import sys
from pathlib import Path

# Ensure root directory and backend directory are in sys.path
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
for p in [str(ROOT_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app import create_app
from backend.init_db import initialize_database
from backend.utils.data_seeder import seed_demo_dataset
from backend.database import resolve_db_path

# Create Flask application instance
app = create_app()

# Auto-initialize and seed database on fresh deploy if it doesn't exist
db_file = resolve_db_path()
if not db_file.exists() or db_file.stat().st_size == 0:
    app.logger.info("Initializing and seeding fresh production database...")
    initialize_database(str(db_file))
    seed_demo_dataset(str(db_file))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
