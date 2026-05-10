import os
import ssl
import uvicorn

from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware


from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


from google.adk.cli.fast_api import get_fast_api_app
from agent.config_load import GetConf
from agent.logging_setup import get_logger
import logging

# 1. Force the root logger to show everything
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")

# 2. Force ADK to reveal LLM responses and internal tool errors
logging.getLogger("google.adk").setLevel(logging.DEBUG)
logging.getLogger("google.adk.models.google_llm").setLevel(logging.DEBUG)
# --------------------------------------------------
# Logger
# --------------------------------------------------
logger = get_logger("AIA_Main")

# --------------------------------------------------
# Optional SSL verification bypass (DEV ONLY)
# --------------------------------------------------
if os.getenv("DISABLE_SSL_VERIFY", "false").lower() == "true":
    try:
        _create_unverified_https_context = ssl._create_unverified_context
    except AttributeError:
        pass
    else:
        ssl._create_default_https_context = _create_unverified_https_context
        logger.warning("SSL certificate verification is DISABLED for this process (dev mode).")

# --------------------------------------------------
# Config
# --------------------------------------------------
config = GetConf.load_configs()

# --------------------------------------------------
# Directory Context
# --------------------------------------------------
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
logger.info(f"Starting AIA Architecture Engine from: {AGENT_DIR}")

# --------------------------------------------------
# Initialize ADK FastAPI App
# --------------------------------------------------
app = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_db_kwargs={"url": config.SESSION_DB_URL},
    web=config.SERVE_WEB_INTERFACE,
)

# --------------------------------------------------
# CORS
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # 💥 ADDED: Expose headers so the frontend streaming client doesn't get blocked
    expose_headers=["*"], 
)

# --------------------------------------------------
# Local Generated Docs Serving
# --------------------------------------------------
GENERATED_DOCS_DIR = Path(os.getenv("GENERATED_DOCS_DIR", "generated_docs")).resolve()
GENERATED_DOCS_DIR.mkdir(parents=True, exist_ok=True)

logger.info("Serving local generated docs from: %s", GENERATED_DOCS_DIR)

app.mount(
    "/generated_docs",
    StaticFiles(directory=str(GENERATED_DOCS_DIR)),
    name="generated_docs",
)


@app.get("/download/{filename}")
async def download_generated_file(filename: str):
    safe_filename = Path(filename).name
    file_path = (GENERATED_DOCS_DIR / safe_filename).resolve()

    if GENERATED_DOCS_DIR not in file_path.parents and file_path != GENERATED_DOCS_DIR:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {safe_filename}")

    return FileResponse(
        path=str(file_path),
        filename=safe_filename,
        media_type="application/octet-stream",
    )
# --------------------------------------------------
# Backend-owned fallback sections
# --------------------------------------------------
FALLBACK_HLD_SECTIONS = [
    "Document Metadata",
    "Project Details",
    "Document Control",
    "Executive Summary",
    "Summary Of Functionality",
    "RAID",
    "Design Decisions",
    "Logical View",
    "Physical View",
    "Process View",
    "Data Flow",
    "Data Storage",
    "Subject Areas",
    "Component Summary",
    "Security Architecture",
    "Compliance Checks",
    "Operational Performance",
    "Cost Considerations",
]

# =====================================================================
# Health Check
# =====================================================================
@app.get("/health")
async def health():
    """
    Lightweight health endpoint for local/dev checks.
    """
    return {"status": "ok"}

# =====================================================================
# Dynamic HLD Sections Endpoint
# =====================================================================
@app.get("/api/hld_sections")
async def get_hld_sections():
    """
    Returns the dynamic list of HLD sections from the Pydantic schema.

    Backend owns fallback handling here.
    """
    try:
        from schema_types.hld_schema import HLDReport

        sections = [
            f_info.title or f_name.replace("_", " ").title()
            for f_name, f_info in HLDReport.model_fields.items()
        ]

        if isinstance(sections, list) and len(sections) > 0:
            return JSONResponse(content=sections)

        logger.warning("HLD schema loaded but resolved section list is empty. Returning backend fallback.")
        return JSONResponse(content=FALLBACK_HLD_SECTIONS, status_code=200)

    except Exception:
        logger.exception("Error fetching schema sections")
        return JSONResponse(content=FALLBACK_HLD_SECTIONS, status_code=200)

# =====================================================================
# Local Development Entry Point
# =====================================================================
if __name__ == "__main__":
    # 💥 Fix: Set reload=False to stop the infinite server restarts
    # 💥 ADDED: timeout_keep_alive extends the connection window so the stream doesn't break during long generations
    uvicorn.run(
        "agent_api:app", 
        host="localhost", 
        port=8000, 
        reload=False,
        timeout_keep_alive=300
    )
