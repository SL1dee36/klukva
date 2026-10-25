"""
Klukva Main Application Entry Point
Fast, lightweight, minimal RAM consumption.
Serves both JSON REST API and Static Utilitarian Frontend.
"""

import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.routes import router as api_router

import sys

def get_frontend_dir() -> str:
    env_f = os.environ.get("KLUKVA_FRONTEND_DIR")
    if env_f and os.path.exists(env_f):
        return os.path.abspath(env_f)

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        parent_dir = os.path.dirname(exe_dir)
        repo_frontend = os.path.join(parent_dir, "frontend")
        if os.path.exists(repo_frontend):
            return repo_frontend
        meipass_frontend = os.path.join(getattr(sys, "_MEIPASS", exe_dir), "frontend")
        if os.path.exists(meipass_frontend):
            return meipass_frontend

    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "frontend")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = get_frontend_dir()

app = FastAPI(
    title="Klukva",
    description="Ultra-lightweight utilitarian task tracker",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router)


# Static assets
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/favicon.ico")
async def favicon():
    fav_path = os.path.join(FRONTEND_DIR, "favicon.svg")
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/svg+xml")
    return {"message": "Favicon not found"}


@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Klukva backend is running. Frontend not found."}


@app.get("/task/{task_id}")
async def task_page(task_id: int):
    # Route for direct task URL deep-linking
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": f"Task {task_id}"}


if __name__ == "__main__":
    print("Starting Klukva on http://127.0.0.1:3002 ...")
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=3002,
        reload=False,
        log_level="info",
        access_log=False
    )
