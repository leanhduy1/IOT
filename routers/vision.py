import io
from typing import List

from fastapi import APIRouter, UploadFile, File
from PIL import Image

from ml import infer_pil

router = APIRouter()

@router.post("/scan")
async def scan(file: UploadFile = File(...)):
    img = Image.open(io.BytesIO(await file.read()))
    return infer_pil(img)

@router.post("/scan3")
async def scan3(files: List[UploadFile] = File(...)):
    files = files[:3] if files else []
    if not files:
        return {"error": "no files"}
    results, votes = [], {}
    for f in files:
        img = Image.open(io.BytesIO(await f.read()))
        out = infer_pil(img)
        results.append(out)
        lab = out["label"]
        votes[lab] = votes.get(lab, 0) + 1
    final_label = max(votes.items(), key=lambda kv: kv[1])[0]
    final_conf = max((r["top1"]["prob"] if r["label"] == final_label else 0.0) for r in results)
    return {
        "final_label": final_label,
        "final_confidence": final_conf,
        "votes": votes,
        "results": results,
        "threshold": results[0]["threshold"],
    }
