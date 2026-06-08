"""
FastAPI app — Epico Pitch Deck Composer.

Endpoints:
  GET  /                      Composer UI
  GET  /api/health            Health check
  POST /api/cvr-lookup        Slå CVR op på navn eller nummer
  POST /api/research          Kør fuld AI-analyse (CVR + PDF + Claude)
  POST /api/generate-deck     Render slutdeck ud fra struktureret data
"""
import os
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cvr import lookup_by_name, lookup_by_cvr
from claude_client import analyze_client, reload_knowledge
from deck_gen import render_deck
from pdf_reader import extract_text
from knowledge_loader import load_summary


load_dotenv(override=True)  # override=True for at trumfe tom shell-var

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent  # epico-pitch-deck/
GENERATED_DIR = BASE_DIR / "generated"
GENERATED_DIR.mkdir(exist_ok=True)


app = FastAPI(title="Epico Pitch Deck Composer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Server frontend statisk
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
app.mount("/generated", StaticFiles(directory=str(GENERATED_DIR)), name="generated")
# Composer-mappens egne assets (composer.css, composer.js)
app.mount("/composer-assets", StaticFiles(directory=str(FRONTEND_DIR / "composer")), name="composer_assets")


# ---------- Models ----------
class CVRLookupRequest(BaseModel):
    query: str
    type: str = "name"  # "name" or "cvr"


class GenerateDeckRequest(BaseModel):
    client_name: str
    analysis: dict
    meeting: Optional[dict] = None
    team: Optional[dict] = None


# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve composer UI."""
    composer_html = FRONTEND_DIR / "composer" / "index.html"
    if composer_html.exists():
        return HTMLResponse(composer_html.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Composer UI ikke fundet</h1><p>Forventede: " + str(composer_html) + "</p>")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "time": datetime.utcnow().isoformat() + "Z",
        "knowledge": load_summary(),
    }


@app.post("/api/reload-knowledge")
async def reload_kb():
    """Reload knowledge base fra disk (efter manuelle .md-redigeringer)."""
    total_chars = reload_knowledge()
    return {"status": "reloaded", "total_chars": total_chars, "summary": load_summary()}


@app.post("/api/cvr-lookup")
async def cvr_lookup(req: CVRLookupRequest):
    """Slå en virksomhed op via CVR-API."""
    if req.type == "cvr":
        result = await lookup_by_cvr(req.query)
    else:
        result = await lookup_by_name(req.query)

    if not result:
        return JSONResponse({"found": False}, status_code=404)
    return {"found": True, "data": result}


@app.post("/api/research")
async def run_research(
    client_name: str = Form(...),
    cvr_number: Optional[str] = Form(None),
    # Lag 1: Strukturerede sælger-inputs
    meeting_stage: Optional[str] = Form("first_touch"),
    meeting_history: Optional[str] = Form(None),
    personal_angle: Optional[str] = Form(None),
    insider_insights: Optional[str] = Form(None),
    exclusions: Optional[str] = Form(None),
    tone: Optional[str] = Form("balanced"),
    # Pitch-vinkel
    pitch_focus: Optional[str] = Form(None),
    services_to_highlight: Optional[str] = Form(None),  # Comma-separated
    emphasis: Optional[str] = Form(None),
    # Lag 2: Slide-for-slide dictation
    dict_why_meeting: Optional[str] = Form(None),
    dict_research_facts: Optional[str] = Form(None),
    dict_priorities: Optional[str] = Form(None),
    dict_mappings: Optional[str] = Form(None),
    dict_next_steps: Optional[str] = Form(None),
    annual_report: Optional[UploadFile] = File(None),
):
    """
    Kør fuld research-pipeline:
    1. Hent CVR-data hvis muligt
    2. Parse uploaded PDF hvis vedhæftet
    3. Kald Claude med alt indhold
    4. Returnér struktureret analyse
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY er ikke sat. Kopier .env.example til .env og indsæt din API-key.",
        )

    # Step 1: CVR-lookup
    cvr_data = None
    if cvr_number:
        cvr_data = await lookup_by_cvr(cvr_number)
    if not cvr_data:
        cvr_data = await lookup_by_name(client_name)

    # Step 2: PDF parsing
    annual_report_text = None
    if annual_report and annual_report.filename:
        pdf_bytes = await annual_report.read()
        try:
            annual_report_text = extract_text(pdf_bytes)
        except Exception as e:
            return JSONResponse(
                {"error": f"Kunne ikke læse PDF: {e}"},
                status_code=400,
            )

    # Parse services-list
    services_list = []
    if services_to_highlight:
        services_list = [s.strip() for s in services_to_highlight.split(",") if s.strip()]

    # Saml sælgers brief (Lag 1)
    seller_brief = {
        "meeting_stage": meeting_stage,
        "meeting_history": meeting_history,
        "personal_angle": personal_angle,
        "insider_insights": insider_insights,
        "exclusions": exclusions,
        "tone": tone,
    }

    # Saml slide-dictation (Lag 2)
    slide_dictation = {
        "why_meeting": dict_why_meeting,
        "research_facts": dict_research_facts,
        "priorities": dict_priorities,
        "mappings": dict_mappings,
        "next_steps": dict_next_steps,
    }

    # Step 3: Claude analyse
    try:
        analysis = analyze_client(
            client_name=client_name,
            cvr_data=cvr_data,
            annual_report_text=annual_report_text,
            seller_brief=seller_brief,
            slide_dictation=slide_dictation,
            pitch_focus=pitch_focus,
            services_to_highlight=services_list,
            emphasis=emphasis,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude-analyse fejlede: {e}")

    return {
        "client_name": client_name,
        "cvr_data": cvr_data,
        "pdf_pages_parsed": annual_report_text.count("--- Side ") if annual_report_text else 0,
        "analysis": analysis,
    }


@app.post("/api/generate-deck")
async def generate_deck(req: GenerateDeckRequest):
    """Render det færdige pitch deck som HTML."""
    html = render_deck(
        client_name=req.client_name,
        analysis=req.analysis,
        meeting=req.meeting,
        team=req.team,
        asset_base="/static",
    )

    # Gem til disk
    safe_name = "".join(c if c.isalnum() else "_" for c in req.client_name).lower()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"{safe_name}-{timestamp}.html"
    out_path = GENERATED_DIR / filename
    out_path.write_text(html, encoding="utf-8")

    return {
        "html": html,
        "filename": filename,
        "url": f"/generated/{filename}",
    }


if __name__ == "__main__":
    import uvicorn
    # Railway sætter $PORT — lokalt bruger vi 8000.
    # Railway kører normalt via Procfile, men dette er fallback.
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run("main:app", host=host, port=port, reload=False)
