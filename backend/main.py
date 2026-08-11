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
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from cvr import lookup_by_name, lookup_by_cvr, CVRUnavailable
from claude_client import (
    analyze_client,
    reload_knowledge,
    refine_slide,
    build_pitch_contract,
    suggest_brief_questions,
)
from deck_gen import render_deck, preview_slide_plan
from slide_library import library_summary, reload_library
from pptx_gen import render_pptx
from pdf_reader import extract_text
from knowledge_loader import load_summary
from web_crawler import crawl as crawl_website
from web_search import gather_web_intelligence


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
    # Styrer hvilke slides fra biblioteket der kommer med
    pitch_length: Optional[str] = "medium"
    services: Optional[list] = None
    stakeholder: Optional[str] = None
    excluded_slide_ids: Optional[list] = None


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
        "slide_library": library_summary(),
    }


@app.post("/api/reload-knowledge")
async def reload_kb():
    """Reload knowledge base + slide-bibliotek fra disk (efter .md-redigeringer)."""
    total_chars = reload_knowledge()
    slide_count = reload_library()
    return {
        "status": "reloaded",
        "total_chars": total_chars,
        "summary": load_summary(),
        "slide_library": {"slides": slide_count, **library_summary()},
    }


@app.get("/api/slide-plan")
async def slide_plan(
    pitch_length: str = "medium",
    services: Optional[str] = None,
    stakeholder: Optional[str] = None,
):
    """
    Vis hvilke slides der ville komme med — uden at generere noget.
    Bruges af Composer til live-overblik når sælger ændrer længde/services.
    """
    service_list = [s.strip() for s in services.split(",") if s.strip()] if services else None
    return preview_slide_plan(
        pitch_length=pitch_length,
        services=service_list,
        stakeholder=stakeholder,
    )


@app.post("/api/cvr-lookup")
async def cvr_lookup(req: CVRLookupRequest):
    """Slå en virksomhed op via CVR-API."""
    try:
        if req.type == "cvr":
            result = await lookup_by_cvr(req.query)
        else:
            result = await lookup_by_name(req.query)
    except CVRUnavailable as e:
        # Ikke det samme som "findes ikke" — sælgeren skal vide at det er
        # registret der er nede, ikke deres stavemåde.
        return JSONResponse(
            {"found": False, "unavailable": True,
             "detail": f"{e}. Udfyld felterne manuelt, eller prøv igen senere."},
            status_code=503,
        )

    if not result:
        return JSONResponse(
            {"found": False,
             "detail": "Ingen virksomhed fundet. Tjek stavemåden, eller indtast CVR-nummeret."},
            status_code=404,
        )
    return {"found": True, "data": result}


async def _try_cvr(cvr_number: Optional[str], client_name: str):
    """Slå CVR op, men lad det aldrig vælte kaldet.

    CVR-data er en bonus — pitchen kan sagtens genereres uden. Er registret
    nede eller kvoten opbrugt, kører vi videre på brief og årsrapport alene.
    """
    try:
        if cvr_number:
            found = await lookup_by_cvr(cvr_number)
            if found:
                return found
        return await lookup_by_name(client_name)
    except CVRUnavailable:
        return None


def _readable_api_error(e: Exception) -> str:
    """Oversæt Anthropic-fejl til noget en sælger kan handle på.

    En sælger midt i en mødeforberedelse skal kunne se forskel på "prøv igen"
    og "kontoen mangler kredit" — de kræver vidt forskellige handlinger.
    """
    msg = str(e)
    low = msg.lower()
    if "credit balance" in low or "insufficient" in low:
        return "Anthropic-kontoen mangler kredit. Tilføj kredit under Plans & Billing og prøv igen."
    if "authentication" in low or "invalid x-api-key" in low or "401" in low:
        return "API-nøglen blev afvist. Tjek ANTHROPIC_API_KEY."
    if "rate limit" in low or "429" in low:
        return "For mange kald til Claude lige nu. Vent et halvt minut og prøv igen."
    if "overloaded" in low or "529" in low:
        return "Claude er overbelastet lige nu. Prøv igen om lidt."
    return f"Kaldet til Claude fejlede: {msg[:300]}"


@app.post("/api/brief-questions")
async def brief_questions(
    client_name: str = Form(...),
    cvr_number: Optional[str] = Form(None),
    pitch_length: Optional[str] = Form("medium"),
    meeting_stage: Optional[str] = Form("first_touch"),
    meeting_stakeholder: Optional[str] = Form(None),
    meeting_history: Optional[str] = Form(None),
    personal_angle: Optional[str] = Form(None),
    insider_insights: Optional[str] = Form(None),
    exclusions: Optional[str] = Form(None),
    pitch_focus: Optional[str] = Form(None),
    services_to_highlight: Optional[str] = Form(None),
):
    """
    Omvendt brief: i stedet for at sælgeren skal gætte hvilke af tolv felter
    der betyder noget, læser vi hvad de har skrevet og spørger om de 2-3 ting
    der faktisk ville løfte pitchen.

    Hurtigt kald (~5 sek) — ét Claude-kald uden research.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY er ikke sat.")

    cvr_data = await _try_cvr(cvr_number, client_name)

    services_list = []
    if services_to_highlight:
        services_list = [s.strip() for s in services_to_highlight.split(",") if s.strip()]

    try:
        result = await run_in_threadpool(
            suggest_brief_questions,
            client_name=client_name,
            cvr_data=cvr_data,
            seller_brief={
                "meeting_stage": meeting_stage,
                "meeting_history": meeting_history,
                "personal_angle": personal_angle,
                "insider_insights": insider_insights,
                "exclusions": exclusions,
            },
            pitch_focus=pitch_focus,
            stakeholder_key=meeting_stakeholder,
            pitch_length=pitch_length,
            services_to_highlight=services_list,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=_readable_api_error(e))

    if not result:
        raise HTTPException(status_code=502, detail="Claude svarede uden spørgsmål. Prøv igen.")

    return result


@app.post("/api/research")
async def run_research(
    client_name: str = Form(...),
    cvr_number: Optional[str] = Form(None),
    pitch_length: Optional[str] = Form("medium"),
    # Lag 1: Strukturerede sælger-inputs
    meeting_stage: Optional[str] = Form("first_touch"),
    meeting_stakeholder: Optional[str] = Form(None),
    meeting_history: Optional[str] = Form(None),
    personal_angle: Optional[str] = Form(None),
    insider_insights: Optional[str] = Form(None),
    exclusions: Optional[str] = Form(None),
    # Pitch-vinkel
    pitch_focus: Optional[str] = Form(None),
    services_to_highlight: Optional[str] = Form(None),  # Comma-separated
    # Lag 2: Slide-for-slide dictation
    dict_research_facts: Optional[str] = Form(None),
    dict_priorities: Optional[str] = Form(None),
    dict_mappings: Optional[str] = Form(None),
    dict_next_steps: Optional[str] = Form(None),
    # Datakilder
    enable_web_search: Optional[str] = Form("true"),
    enable_website_crawl: Optional[str] = Form("true"),
    annual_report: Optional[UploadFile] = File(None),
):
    """
    Kør fuld research-pipeline — brief FØRST, research bagefter.

    Rækkefølgen er bevidst: pitch-kontrakten bygges på sælgers brief og CVR alene,
    og dét er kontrakten der bestemmer hvad der bliver søgt efter. Omvendt rækkefølge
    ville give os generisk firmanyt, som pitchen så skulle presses ned over.

    1. CVR-opslag
    2. Parse årsrapport-PDF hvis vedhæftet
    3. Byg pitch-kontrakt (brief + CVR + årsrapport) → giver research_queries
    4. Målrettet web-search efter kontraktens spørgsmål + crawl
    5. Claude-analyse bundet til kontrakten
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY er ikke sat. Kopier .env.example til .env og indsæt din API-key.",
        )

    # ── Step 1: CVR-lookup ──
    cvr_data = await _try_cvr(cvr_number, client_name)

    # ── Step 2: Parse årsrapport ──
    annual_report_text = None
    if annual_report and annual_report.filename:
        pdf_bytes = await annual_report.read()
        try:
            annual_report_text = extract_text(pdf_bytes)
        except Exception as e:
            return JSONResponse({"error": f"Kunne ikke læse PDF: {e}"}, status_code=400)

    services_list = []
    if services_to_highlight:
        services_list = [s.strip() for s in services_to_highlight.split(",") if s.strip()]

    seller_brief = {
        "meeting_stage": meeting_stage,
        "meeting_history": meeting_history,
        "personal_angle": personal_angle,
        "insider_insights": insider_insights,
        "exclusions": exclusions,
    }

    slide_dictation = {
        "research_facts": dict_research_facts,
        "priorities": dict_priorities,
        "mappings": dict_mappings,
        "next_steps": dict_next_steps,
    }

    # ── Step 3: Pitch-kontrakt FØR research ──
    # Kontrakten ved endnu intet om web-fund. Det er pointen: den beslutter
    # hvad mødet handler om, og udleder derfra hvad vi mangler at få afklaret.
    pitch_contract = await run_in_threadpool(
        build_pitch_contract,
        client_name=client_name,
        cvr_data=cvr_data,
        annual_report_text=annual_report_text,
        seller_brief=seller_brief,
        slide_dictation=slide_dictation,
        pitch_focus=pitch_focus,
        services_to_highlight=services_list,
        stakeholder_key=meeting_stakeholder,
        pitch_length=pitch_length,
    )

    # ── Step 4: Målrettet research ──
    website_data = None
    if enable_website_crawl == "true" and cvr_data and cvr_data.get("website"):
        try:
            website_data = await crawl_website(cvr_data["website"], max_pages=6)
        except Exception:
            website_data = None  # Ikke kritisk

    web_intelligence = None
    if enable_web_search == "true":
        try:
            web_intelligence = await run_in_threadpool(
                gather_web_intelligence,
                client_name=client_name,
                industry_hint=cvr_data.get("industry_desc") if cvr_data else None,
                pitch_focus=pitch_focus,
                research_queries=(pitch_contract or {}).get("research_queries"),
                core_intent=(pitch_contract or {}).get("core_intent"),
                max_searches=4,
            )
        except Exception:
            web_intelligence = None

    # ── Step 5: Analyse, bundet til kontrakten ──
    try:
        analysis = await run_in_threadpool(
            analyze_client,
            client_name=client_name,
            cvr_data=cvr_data,
            annual_report_text=annual_report_text,
            website_text=website_data.get("consolidated_text") if website_data else None,
            web_intelligence=web_intelligence.get("summary") if web_intelligence else None,
            seller_brief=seller_brief,
            slide_dictation=slide_dictation,
            pitch_focus=pitch_focus,
            services_to_highlight=services_list,
            stakeholder_key=meeting_stakeholder,
            pitch_length=pitch_length,
            pitch_contract=pitch_contract,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=_readable_api_error(e))

    return {
        "client_name": client_name,
        "cvr_data": cvr_data,
        "pdf_pages_parsed": annual_report_text.count("--- Side ") if annual_report_text else 0,
        "website_pages_crawled": len(website_data["pages"]) if website_data else 0,
        "web_searches_performed": web_intelligence.get("search_count", 0) if web_intelligence else 0,
        "pitch_contract": pitch_contract,
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
        pitch_length=req.pitch_length or "medium",
        services=req.services,
        stakeholder=req.stakeholder,
        excluded_slide_ids=req.excluded_slide_ids,
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


class RefineSlideRequest(BaseModel):
    slide_type: str
    current_content: object
    directive: str
    client_name: Optional[str] = None
    stakeholder_key: Optional[str] = None


@app.post("/api/refine-slide")
async def refine_slide_endpoint(req: RefineSlideRequest):
    """Skærp et specifikt slide via Claude. Returnér forbedret indhold."""
    try:
        refined = await run_in_threadpool(
            refine_slide,
            slide_type=req.slide_type,
            current_content=req.current_content,
            directive=req.directive,
            client_name=req.client_name,
            stakeholder_key=req.stakeholder_key,
        )
        return {"refined_content": refined}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Slide-skærpning fejlede: {e}")


@app.post("/api/generate-deck-pptx")
async def generate_deck_pptx(req: GenerateDeckRequest):
    """Render det færdige pitch deck som .pptx fil og returnér til download."""
    pptx_bytes = render_pptx(
        client_name=req.client_name,
        analysis=req.analysis,
        meeting=req.meeting,
        team=req.team,
        pitch_length=req.pitch_length or "medium",
        services=req.services,
        stakeholder=req.stakeholder,
        excluded_slide_ids=req.excluded_slide_ids,
    )

    safe_name = "".join(c if c.isalnum() else "_" for c in req.client_name).lower()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"epico-pitch-{safe_name}-{timestamp}.pptx"

    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn
    # Railway sætter $PORT — lokalt bruger vi 8000.
    # Railway kører normalt via Procfile, men dette er fallback.
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run("main:app", host=host, port=port, reload=False)
