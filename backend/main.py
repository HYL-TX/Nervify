# backend/main.py
#
# Application entry point: builds the FastAPI app, wires CORS, serves the
# frontend assets, mounts the route modules, and starts the serial reader.
# Run with `uvicorn backend.main:app --reload`.

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, serial_io
from .routes import mvc, session, system, trial

app = FastAPI(title="Nervify NME Measurement API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend's CSS/JS (index.html itself is served by GET /ui).
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")

app.include_router(system.router)
app.include_router(session.router)
app.include_router(mvc.router)
app.include_router(trial.router)

serial_io.start_serial_reader()
