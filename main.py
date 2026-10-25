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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

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
