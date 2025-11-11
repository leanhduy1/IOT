from pathlib import Path
from typing import List
import numpy as np
from PIL import Image, ImageOps
from tensorflow import keras

from core.config import MODEL_PATH, LABELS_PATH, IMG_SIZE, THRESHOLD

# ---------- Nạp labels ----------
def _load_labels(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"labels file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    out: List[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        out.append(ln.split(" ", 1)[1] if " " in ln else ln)
    return out

labels: List[str] = _load_labels(Path(LABELS_PATH))

# ---------- Nạp model SavedModel----------
if not Path(MODEL_PATH).exists():
    raise FileNotFoundError(f"model not found: {MODEL_PATH}")

tm = keras.layers.TFSMLayer(str(MODEL_PATH), call_endpoint="serving_default")

# ---------- Tiền xử lý ảnh ----------
def preprocess(img: Image.Image) -> np.ndarray:
    img = img.convert("RGB")
    img = ImageOps.fit(img, (IMG_SIZE, IMG_SIZE), Image.Resampling.LANCZOS)
    arr = np.asarray(img).astype(np.float32)
    arr = (arr / 127.5) - 1.0
    return np.expand_dims(arr, 0)

# ---------- Suy luận ----------
def infer_logits(x: np.ndarray) -> np.ndarray:
    out = tm(x)
    y = next(iter(out.values())) if isinstance(out, dict) else out
    return y.numpy()[0]

def infer_one(x: np.ndarray) -> dict:
    probs = infer_logits(x)
    top = int(np.argmax(probs))
    p = float(probs[top])

    order = np.argsort(probs)[::-1]
    top2 = int(order[1]) if order.size > 1 else top

    label = labels[top] if p >= THRESHOLD else "unknown"

    return {
        "label": label,
        "confidence": p,
        "top1": {"index": top, "label": labels[top], "prob": p},
        "top2": {"index": top2, "label": labels[top2], "prob": float(probs[top2])},
    }

def infer_pil(img: Image.Image) -> dict:
    x = preprocess(img)
    return infer_one(x)
