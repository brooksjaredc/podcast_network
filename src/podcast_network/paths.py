from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LEGACY_DATA_DIR = DATA_DIR / "legacy"
LEGACY_ANALYSIS_DIR = LEGACY_DATA_DIR / "analysis"
LEGACY_APP_DIR = LEGACY_DATA_DIR / "app"
