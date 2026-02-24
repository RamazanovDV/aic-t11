import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.app import create_app
from backend.app.config import config

app = create_app()

if __name__ == "__main__":
    print(f"Starting backend on {config.host}:{config.port}")
    app.run(host=config.host, port=config.port, debug=True)
