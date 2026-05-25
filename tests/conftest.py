from pathlib import Path
import sys


CORE_SRC = Path(__file__).resolve().parents[1] / 'packages' / 'core' / 'src'
BACKEND_SRC = Path(__file__).resolve().parents[1] / 'apps' / 'backend' / 'src'
PLUGIN_SYSTEM_SRC = Path(__file__).resolve().parents[1] / 'packages' / 'plugin_system' / 'src'

if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

if str(PLUGIN_SYSTEM_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SYSTEM_SRC))
