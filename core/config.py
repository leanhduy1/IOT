from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv()

BASE = Path(__file__).resolve().parents[1]
MODEL_PATH = (BASE / os.getenv("MODEL_PATH", "models/model.savedmodel")).resolve()
LABELS_PATH = (BASE / os.getenv("LABELS_PATH", "models/labels.txt")).resolve()
IMG_SIZE = int(os.getenv("IMG_SIZE", "224"))
THRESHOLD = float(os.getenv("THRESHOLD", "0.90"))
DB_PATH = os.getenv("DB_PATH", str(BASE / "data/app.db"))
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "storage")).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
