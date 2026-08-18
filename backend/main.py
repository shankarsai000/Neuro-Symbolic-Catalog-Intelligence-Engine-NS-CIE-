from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.reviews import router as reviews_router
from app.api.routes import router as core_router
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize persistent database schema on startup
    await init_db()
    yield


app = FastAPI(
    title="NS-CIE Backend",
    description="Neuro-Symbolic Catalog Intelligence Engine API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for Docker container internal networking
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core_router)
app.include_router(reviews_router)
