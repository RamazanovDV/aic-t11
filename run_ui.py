import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ui.app import create_app, ui_config

app = create_app()

if __name__ == "__main__":
    print(f"Starting UI on {ui_config.host}:{ui_config.port}")
    app.run(host=ui_config.host, port=ui_config.port, debug=True)
