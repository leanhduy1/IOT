from pathlib import Path
from typing import List
import numpy as np
from PIL import Image, ImageOps
from tensorflow import keras

from core.config import MODEL_PATH, LABELS_PATH, IMG_SIZE, THRESHOLD


def _load_labels(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"labels file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.split(" ", 1)[1] if " " in ln else ln for ln in lines if ln.strip()]


labels: List[str] = _load_labels(Path(LABELS_PATH))

if not Path(MODEL_PATH).exists():
    raise FileNotFoundError(f"model not found: {MODEL_PATH}")

tm = keras.layers.TFSMLayer(str(MODEL_PATH), call_endpoint="serving_default")


def preprocess(img: Image.Image) -> np.ndarray:
    # Đảm bảo ảnh là RGB (phòng trường hợp ESP32 gửi Grayscale)
    if img.mode != "RGB":
        img = img.convert("RGB")

    img = ImageOps.fit(img, (IMG_SIZE, IMG_SIZE), Image.Resampling.LANCZOS)

    # Chuẩn hóa giá trị pixel về [-1, 1]
    arr = np.asarray(img).astype(np.float32)
    arr = (arr / 127.5) - 1.0
    return np.expand_dims(arr, 0)


def infer_one(x: np.ndarray) -> dict:
    out = tm(x)

    probs = list(out.values())[0].numpy()[0]

    top = int(np.argmax(probs))
    p = float(probs[top])

    order = np.argsort(probs)[::-1]
    top2 = int(order[1]) if order.size > 1 else top

    final_label = labels[top] if p >= THRESHOLD else "unknown"

    return {
        "label": final_label,
        "confidence": p,
        "top1": {"index": top, "label": labels[top], "prob": p},
        "top2": {
            "index": top2,
            "label": labels[top2],
            "prob": float(probs[top2])
        },
    }


def infer_pil(img: Image.Image) -> dict:
    try:
        x = preprocess(img)
        return infer_one(x)
    except Exception as e:
        return {
            "label": "unknown",
            "confidence": 0.0,
            "top1": {"index": -1, "label": "error", "prob": 0.0},
            "top2": {"index": -1, "label": "error", "prob": 0.0},
        }