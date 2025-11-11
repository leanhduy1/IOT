from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config import DB_PATH, LABELS_PATH
from db import connect, init, seed_products_from_labels
from routers import vision

CON = connect(DB_PATH)
init(CON)
seed_products_from_labels(CON, str(LABELS_PATH), default_price=10000)

app = FastAPI(title="TM Classifier", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(vision.router)
