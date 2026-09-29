"""
FastAPI app — Epico Pitch Deck Composer.

Endpoints:
  GET  /                      Composer UI
  GET  /api/health            Health check
  POST /api/cvr-lookup        Slå CVR op på navn eller nummer
  POST /api/research          Kør fuld AI-analyse (CVR + PDF + Claude)
  POST /api/generate-deck     Render slutdeck ud fra struktureret data

Agent-API (X-Api-Key), bruges af Copilot og Epico Engage:
  GET  /agent/catalogue                    Sprog, services, kapitler, plan og import-info
  GET  /agent/plan                         Slide-plan for en længde + services
  GET  /agent/slides/{id}/thumbnail        JPEG 640x360 (lang cache)
  GET  /agent/slides/{id}/preview          Én slide som selvstændig HTML-side
  POST /agent/master-deck                  Masterdeck med kundens navn (+ html)
  POST /agent/deck/pdf                     Samme deck som PDF (kræver Chromium)
"""
import os
import re
import json
import hmac
import hashlib
import time
import uuid
import secrets
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, UploadFile, File, Form, Header, HTTPException, Request
from fastapi.openapi.utils import get_openapi
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
    _strip_long_dashes,
)
import master_deck
from chromium import ChromiumUnavailable, render_pdf
from deck_gen import render_deck, render_master_deck, preview_slide_plan
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

# Genererede decks ligger på /generated uden nøgle, så filnavnet skal være
# ugætteligt (secrets.token_hex), og gamle filer skal væk igen. 24 timer er
# rigeligt til at præsentere og downloade; Engage gemmer selv det den bruger.
_GENERATED_TTL_SECONDS = 24 * 3600


def _cleanup_generated() -> int:
    """Slet genererede filer ældre end 24 timer. Kaldes ved opstart og ved hver generering."""
    now = time.time()
    removed = 0
    for f in GENERATED_DIR.iterdir():
        try:
            if f.is_file() and now - f.stat().st_mtime > _GENERATED_TTL_SECONDS:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def _safe_name(client_name: str) -> str:
    """Kundenavn som filnavns-led: kun bogstaver og tal, resten bliver underscore."""
    return "".join(c if c.isalnum() else "_" for c in client_name).lower() or "deck"


_cleanup_generated()


app = FastAPI(title="Epico Pitch Deck Composer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# /static serverede tidligere hele repo-roden, inkl. backend/ med kildekode og
# knowledge/. Nu serveres kun de filer composeren faktisk bruger (whitelist).
# Composerens egne filer ligger på /composer-assets, master-slides inlines.
_PUBLIC_FILES = {
    "styles.css": FRONTEND_DIR / "styles.css",  # brand-tokens, bruges af composer/index.html
}


@app.get("/static/{path:path}", include_in_schema=False)
async def static_whitelist(path: str):
    target = _PUBLIC_FILES.get(path)
    if target is None or not target.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(str(target))


app.mount("/generated", StaticFiles(directory=str(GENERATED_DIR)), name="generated")
# Composer-mappens egne assets (composer.css, composer.js)
app.mount("/composer-assets", StaticFiles(directory=str(FRONTEND_DIR / "composer")), name="composer_assets")


@app.middleware("http")
async def _fresh_ui_after_deploy(request, call_next):
    """UI-filer skal revalideres ved hver visning (Cache-Control: no-cache).

    Uden cache-headers gætter browseren sig til friskheden og kan holde fast
    i gammel CSS/JS længe efter en deploy — sælgeren ser så hverken nye
    features eller designrettelser. no-cache betyder ikke "cache aldrig",
    men "spørg serveren først": uændrede filer svarer 304 og koster intet.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith(("/static", "/composer-assets")):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------- Models ----------
class CVRLookupRequest(BaseModel):
    query: str
    type: str = "name"  # "name" or "cvr"


class GenerateDeckRequest(BaseModel):
    client_name: str
    analysis: dict
    meeting: Optional[dict] = None
    team: Optional[dict] = None
    # Styrer hvilke slides fra masterdecket der kommer med
    pitch_length: Optional[str] = "medium"
    services: Optional[list] = None
    stakeholder: Optional[str] = None
    excluded_slide_ids: Optional[list] = None
    # Sælgerens fulde valg fra slide-vælgeren — vinder over forvalget
    selected_slide_ids: Optional[list] = None
    lang: Optional[str] = None


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
    Slides kommer fra masterdecket; default_on angiver forvalget.
    """
    service_list = [s.strip() for s in services.split(",") if s.strip()] if services else None
    return {
        "pitch_length": pitch_length,
        "client_slides": [
            {"title": "Titel (med kundens navn)"},
            {"title": "Research"},
            {"title": "Jeres prioriteter"},
            {"title": "Udfordring → løsning"},
            {"title": "Relevant case"},
        ],
        "library_slides": master_deck.plan(pitch_length, service_list),
        "closing_slides": [
            {"title": "Næste skridt"},
            {"title": "Afslutning"},
        ],
        "chapter_labels": master_deck.CHAPTER_LABELS,
    }


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



# ─── Research-job ─────────────────────────────────────────────────────
# En fuld research-kørsel tager 4-5 minutter. Holdt vi HTTP-forbindelsen åben
# så længe, skar Railways proxy den over ved 300 sekunder og svarede "upstream
# error" i ren tekst — sælgeren mistede hele kørslen få sekunder før den var
# færdig. Nu starter kaldet et job og svarer med det samme; klienten spørger til
# status undervejs.
#
# Jobbene ligger i hukommelsen. Det er bevidst: værktøjet kører én proces med
# nogle få samtidige brugere, og en genstart midt i en kørsel er sjælden nok til
# at "kør igen" er et rimeligt svar. Skal det skaleres til flere processer, skal
# det her flyttes til Redis eller en database.

_RESEARCH_JOBS: Dict[str, Dict[str, Any]] = {}
_JOB_TTL_SECONDS = 3600
_JOB_MAX = 50

# Trin-id'erne matcher dem composeren viser, så statusvisningen er ægte
# fremdrift og ikke bare en animation.
RESEARCH_STEPS = ["cvr", "pdf", "crawl", "websearch", "claude", "done"]


def _new_job() -> str:
    """Opret et job og ryd op i de gamle."""
    now = time.time()
    stale = [k for k, v in _RESEARCH_JOBS.items() if now - v["created"] > _JOB_TTL_SECONDS]
    for k in stale:
        _RESEARCH_JOBS.pop(k, None)
    while len(_RESEARCH_JOBS) >= _JOB_MAX:
        oldest = min(_RESEARCH_JOBS, key=lambda k: _RESEARCH_JOBS[k]["created"])
        _RESEARCH_JOBS.pop(oldest, None)

    job_id = uuid.uuid4().hex[:16]
    _RESEARCH_JOBS[job_id] = {
        "created": now,
        "status": "running",
        "step": "cvr",
        "done_steps": [],
        "result": None,
        "error": None,
    }
    return job_id


def _job_step(job_id: str, step: str) -> None:
    job = _RESEARCH_JOBS.get(job_id)
    if not job:
        return
    prev = job.get("step")
    if prev and prev not in job["done_steps"]:
        job["done_steps"].append(prev)
    job["step"] = step


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


def _slide_catalogue(pitch_length: str, services: list) -> list:
    """Master-slides i det format spørgsmåls-prompten forventer.

    plan() giver rå kapitel-nøgler; AI'en skal se de læsbare navne, ellers
    grupperer den forkert i sit forslag.
    """
    return [
        {
            "id": s["id"],
            "title": s["title"],
            "chapter": master_deck.CHAPTER_LABELS.get(s["category"], s["category"]),
            "services": ", ".join(x.replace("Epico ", "") for x in s["services"]),
        }
        for s in master_deck.plan(pitch_length, services)
    ]


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
    round_number: Optional[int] = Form(1),
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
            slide_catalogue=_slide_catalogue(pitch_length, services_list),
            round_number=max(1, int(round_number or 1)),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=_readable_api_error(e))

    if not result:
        raise HTTPException(status_code=502, detail="Claude svarede uden spørgsmål. Prøv igen.")

    return result


@app.post("/api/research")
async def start_research(
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
    selected_slide_ids: Optional[str] = Form(None),  # komma-separeret
    lang: Optional[str] = Form(None),
    annual_report: Optional[UploadFile] = File(None),
):
    """Start en research-kørsel og svar med det samme.

    Kørslen tager 4-5 minutter. Holdt vi forbindelsen åben så længe, skar
    Railways proxy den over ved 300 sekunder og svarede "upstream error" i ren
    tekst — sælgeren mistede hele kørslen få sekunder før den var færdig.
    Klienten spørger i stedet til `/api/research/{job_id}` undervejs.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY er ikke sat. Kopier .env.example til .env og indsæt din API-key.",
        )

    # Filen skal læses her — den lever kun så længe requesten gør
    pdf_bytes = None
    if annual_report and annual_report.filename:
        pdf_bytes = await annual_report.read()

    job_id = _new_job()
    asyncio.create_task(_do_research(
        job_id,
        client_name=client_name, cvr_number=cvr_number, pitch_length=pitch_length,
        meeting_stage=meeting_stage, meeting_stakeholder=meeting_stakeholder,
        meeting_history=meeting_history, personal_angle=personal_angle,
        insider_insights=insider_insights, exclusions=exclusions,
        pitch_focus=pitch_focus, services_to_highlight=services_to_highlight,
        dict_research_facts=dict_research_facts, dict_priorities=dict_priorities,
        dict_mappings=dict_mappings, dict_next_steps=dict_next_steps,
        enable_web_search=enable_web_search, enable_website_crawl=enable_website_crawl,
        selected_slide_ids=selected_slide_ids, lang=lang, pdf_bytes=pdf_bytes,
    ))
    return {"job_id": job_id, "status": "running", "step": "cvr"}


@app.get("/api/research/{job_id}")
async def research_status(job_id: str):
    """Hvor langt er kørslen? Klienten spørger hvert par sekunder."""
    job = _RESEARCH_JOBS.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Kørslen blev ikke fundet. Serveren er muligvis genstartet — kør research igen.",
        )
    out = {
        "status": job["status"],
        "step": job["step"],
        "done_steps": job["done_steps"],
    }
    if job["status"] == "done":
        out["result"] = job["result"]
    if job["status"] == "error":
        out["detail"] = job["error"]
    return out


async def _do_research(
    job_id: str, *,
    client_name: str, cvr_number, pitch_length,
    meeting_stage, meeting_stakeholder, meeting_history, personal_angle,
    insider_insights, exclusions, pitch_focus, services_to_highlight,
    dict_research_facts, dict_priorities, dict_mappings, dict_next_steps,
    enable_web_search, enable_website_crawl, selected_slide_ids, lang, pdf_bytes,
):
    """Selve kørslen. Rækkefølgen er bevidst: pitch-kontrakten bygges på sælgers
    brief og CVR alene, og dét er kontrakten der bestemmer hvad der bliver søgt
    efter. Omvendt rækkefølge ville give os generisk firmanyt, som pitchen så
    skulle presses ned over.
    """
    job = _RESEARCH_JOBS.get(job_id)
    if job is None:
        return

    try:
        # ── CVR ──
        _job_step(job_id, "cvr")
        cvr_data = await _try_cvr(cvr_number, client_name)

        # ── Årsrapport ──
        _job_step(job_id, "pdf")
        annual_report_text = None
        if pdf_bytes:
            try:
                annual_report_text = extract_text(pdf_bytes)
            except Exception as e:
                job.update(status="error", error=f"Kunne ikke læse PDF: {e}")
                return

        services_list = []
        if services_to_highlight:
            services_list = [x.strip() for x in services_to_highlight.split(",") if x.strip()]

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

        # AI'en skal vide hvilke master-slides der følger, så den kan pege på dem
        # i stedet for at genforklare dem
        picked = [x.strip() for x in (selected_slide_ids or "").split(",") if x.strip()]
        if not picked:
            picked = master_deck.default_slide_ids(pitch_length, services_list)
        master_slides = master_deck.slides_following(picked)

        # ── Kontrakt FØR research ──
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

        # ── Målrettet research ──
        _job_step(job_id, "crawl")
        website_data = None
        if enable_website_crawl == "true" and cvr_data and cvr_data.get("website"):
            try:
                website_data = await crawl_website(cvr_data["website"], max_pages=6)
            except Exception:
                website_data = None  # Ikke kritisk

        _job_step(job_id, "websearch")
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

        # ── Analyse, bundet til kontrakten ──
        _job_step(job_id, "claude")
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
            master_slides=master_slides,
            lang=master_deck.resolve_lang(lang),
        )

        _job_step(job_id, "done")
        job.update(status="done", result={
            "client_name": client_name,
            "cvr_data": cvr_data,
            "pdf_pages_parsed": annual_report_text.count("--- Side ") if annual_report_text else 0,
            "website_pages_crawled": len(website_data["pages"]) if website_data else 0,
            "web_searches_performed": web_intelligence.get("search_count", 0) if web_intelligence else 0,
            "pitch_contract": pitch_contract,
            "analysis": analysis,
        })

    except Exception as e:
        job.update(status="error", error=_readable_api_error(e))


@app.get("/api/languages")
async def languages():
    """Hvilke sprog masterdecket er importeret på — UI'et må kun tilbyde dem."""
    have = master_deck.available_languages()
    return {
        "available": [{"code": c, "label": master_deck.LANGUAGES[c]} for c in have],
        "default": master_deck.resolve_lang(None),
    }


@app.get("/api/master-preview", response_class=HTMLResponse)
async def master_preview(lang: Optional[str] = None):
    """Miniaturer af alle valgbare master-slides — vælgeren i composeren.

    Sælgeren skal kunne se hvad han slår til og fra. En titel som "Fra A til Z"
    siger intet uden sliden ved siden af.

    Siden er ~850 KB fordi billederne inlines (masterens slides refererer dem
    som bare uuid'er uden filendelse, så en statisk rute ville ikke matche).
    Den hentes én gang pr. sidevisning — til- og fravalg går via postMessage,
    ikke ved genindlæsning — og ETag'en gør gentagne besøg gratis.
    """
    if not master_deck.deck_available(master_deck.resolve_lang(lang)):
        raise HTTPException(status_code=503, detail="Masterdecket er ikke indlæst.")

    html = master_deck.inline_assets(master_deck.thumbnails_html(lang), lang)
    etag = '"' + hashlib.sha256(html.encode()).hexdigest()[:16] + '"'
    return HTMLResponse(html, headers={"ETag": etag, "Cache-Control": "private, max-age=300"})


@app.post("/api/generate-deck")
async def generate_deck(req: GenerateDeckRequest):
    """Render det færdige pitch deck som HTML (masterdeckets design)."""
    lang = master_deck.resolve_lang(req.lang)
    html = render_master_deck(
        client_name=req.client_name,
        analysis=req.analysis,
        meeting=req.meeting,
        team=req.team,
        pitch_length=req.pitch_length or "medium",
        services=req.services,
        excluded_slide_ids=req.excluded_slide_ids,
        selected_slide_ids=req.selected_slide_ids,
        lang=lang,
    )

    # Gem til disk. Sproget er med i navnet, og det tilfældige led gør at URL'en
    # på /generated ikke kan gættes ud fra kundenavn og tidspunkt.
    _cleanup_generated()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"{_safe_name(req.client_name)}-{lang}-{timestamp}-{secrets.token_hex(8)}.html"
    out_path = GENERATED_DIR / filename
    out_path.write_text(html, encoding="utf-8")

    return {
        "html": html,
        "filename": filename,
        "url": f"/generated/{filename}",
    }


class UpdateDeckSlidesRequest(BaseModel):
    filename: str
    edits: Dict[str, str]


@app.post("/api/update-deck-slides")
async def update_deck_slides(req: UpdateDeckSlidesRequest):
    """Skriv sælgerens tekstredigeringer ind i den genererede deck-fil.

    Composeren lader sælgeren redigere slide-tekst direkte i deck-visningen.
    Her persisteres ændringerne i selve HTML-filen, så download og deling
    matcher det sælgeren ser — også efter decket er regenereret.
    """
    name = Path(req.filename).name
    if name != req.filename or not name.endswith(".html"):
        raise HTTPException(status_code=400, detail="Ugyldigt filnavn.")
    path = GENERATED_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Decket findes ikke længere. Generer det igen.")

    html = path.read_text(encoding="utf-8")
    updated = 0
    for slide_id, inner in req.edits.items():
        if not re.fullmatch(r"[\w-]+", slide_id):
            continue
        # Redigeringsattributter må ikke ende i filen, og tankestreger er
        # bandlyst i deck-tekst uanset om de er tastet ind manuelt
        inner = re.sub(r'\s+(?:contenteditable|spellcheck)="[^"]*"', "", inner)
        inner = _strip_long_dashes(inner)
        pattern = re.compile(
            rf'(<section[^>]*data-slide-id="{re.escape(slide_id)}"[^>]*>).*?(</section>)',
            re.S,
        )
        html, n = pattern.subn(
            lambda m, inner=inner: m.group(1) + inner + m.group(2), html, count=1
        )
        updated += n

    path.write_text(html, encoding="utf-8")
    return {"updated": updated}


class RefineSlideRequest(BaseModel):
    slide_type: str
    current_content: object
    directive: str
    client_name: Optional[str] = None
    stakeholder_key: Optional[str] = None
    lang: Optional[str] = None


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
            lang=master_deck.resolve_lang(req.lang),
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

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"epico-pitch-{_safe_name(req.client_name)}-{timestamp}.pptx"

    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==================== AGENT-API ====================
# Sikret under-API på /agent til eksterne assistenter (Copilot Studio,
# ChatGPT Actions, MCP-klienter). Holdes adskilt fra /api, så composerens
# egen UI kan blive ved med at kalde frit, mens alt hvad assistenter kan nå
# kræver API-nøgle. Under-app'en genererer sin egen OpenAPI-beskrivelse på
# /agent/openapi.json — det er den fil Copilot Studio importerer.

_AGENT_KEY_ENV = "PITCH_AGENT_API_KEY"


def _public_base(request: Request) -> str:
    """Absolut base-URL til links i svar. Assistenten viser URL'en til
    sælgeren, så den skal kunne åbnes udefra — ikke være relativ."""
    env = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if env:
        return env if env.startswith("http") else f"https://{env}"
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.url.netloc}"


async def _require_agent_key(x_api_key: Optional[str] = Header(None, alias="X-Api-Key")):
    expected = os.environ.get(_AGENT_KEY_ENV)
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=f"Agent-API'et er ikke aktiveret. Sæt miljøvariablen {_AGENT_KEY_ENV} på serveren.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Ugyldig eller manglende API-nøgle (header X-Api-Key).")


agent_app = FastAPI(
    title="Epico Pitch Composer – Agent API",
    version="1.0.0",
    description=(
        "API til at generere Epico pitch decks fra en assistent (Copilot, ChatGPT m.fl.). "
        "To veje: (1) hurtigt masterdeck med kundens navn på coveret via /master-deck, "
        "(2) skræddersyet deck: start research med /research, følg status på /research/{job_id} "
        "(tager 4-5 minutter), og generér decket med /deck-from-research når researchen er færdig. "
        "Svar altid sælgeren med deck-linket."
    ),
    dependencies=[Depends(_require_agent_key)],
)


class AgentMasterDeckRequest(BaseModel):
    client_name: str
    lang: Optional[str] = "da"
    pitch_length: Optional[str] = "medium"
    services: Optional[List[str]] = None
    selected_slide_ids: Optional[List[str]] = None
    contact_person: Optional[str] = None
    date: Optional[str] = None
    # Engage gemmer selv decket og skal ikke stole på filer på vores disk
    include_html: bool = False


class AgentResearchRequest(BaseModel):
    client_name: str
    lang: Optional[str] = "da"
    brief: Optional[str] = None
    stakeholder: Optional[str] = None
    pitch_length: Optional[str] = "medium"
    services: Optional[List[str]] = None
    cvr_number: Optional[str] = None


class AgentDeckFromResearchRequest(BaseModel):
    job_id: str
    selected_slide_ids: Optional[List[str]] = None
    contact_person: Optional[str] = None
    include_html: bool = False


_PITCH_LENGTHS = ["short", "medium", "long"]
_SERVICES = [
    "Epico Freelance", "Epico Projektansættelser", "Epico NextGen",
    "Epico Search", "Epico Solution", "Epico Public",
]


def _service_list(services: Optional[str]) -> Optional[List[str]]:
    """Komma-separeret query-param til liste. None hvis tom."""
    if not services:
        return None
    return [s.strip() for s in services.split(",") if s.strip()] or None


def _plan_payload(lang: Optional[str], pitch_length: str, services: Optional[str]) -> Dict[str, Any]:
    """Det Engage skal bruge til sin Slides-fane: alle valgbare slides med
    forvalg og grund, kapitler i deck-rækkefølge, og hvad der kan vælges."""
    if pitch_length not in _PITCH_LENGTHS:
        raise HTTPException(status_code=400, detail=f"pitch_length skal være en af {_PITCH_LENGTHS}.")
    lang = master_deck.resolve_lang(lang)
    service_list = _service_list(services)
    slides = [
        {
            "id": d["id"],
            "title": d["title"],
            "chapter": d["category"],
            "chapter_label": master_deck.CHAPTER_LABELS.get(d["category"], d["category"]),
            "default_on": d["default_on"],
            "off_reason": d["off_reason"],
            "unlock_services": d.get("unlock_services", []),
            "lengths": d["lengths"],
            "services": d["services"],
        }
        for d in master_deck.plan(pitch_length, service_list)
    ]
    return {
        "lang": lang,
        "pitch_length": pitch_length,
        "services": service_list or [],
        "pitch_lengths": list(_PITCH_LENGTHS),
        "available_services": list(_SERVICES),
        "chapters": master_deck.deck_chapters(),
        "slides": slides,
    }


@agent_app.get("/catalogue", summary="Hent gyldige værdier: sprog, services, stakeholdere, slides og plan")
async def agent_catalogue(
    lang: Optional[str] = None,
    pitch_length: str = "medium",
    services: Optional[str] = None,
):
    """Slå op hvad der kan vælges, før du kalder de andre endpoints.
    Brug service-navnene ordret i `services` og slide-id'erne i
    `selected_slide_ids`. Udelades `selected_slide_ids` vælger systemet
    selv slides ud fra mødelængde og services.

    `plan` viser forvalget for `pitch_length` og `services` (komma-separeret),
    med kapitler i deck-rækkefølge. `source` fortæller hvilken masterfil der
    er importeret og hvornår."""
    plan = _plan_payload(lang, pitch_length, services)
    return {
        "languages": master_deck.available_languages(),
        "default_language": master_deck.resolve_lang(None),
        "pitch_lengths": list(_PITCH_LENGTHS),
        "services": list(_SERVICES),
        "stakeholders": [
            "procurement", "it-leader", "tech-lead", "hr-leader",
            "cfo", "executive", "business-leader",
        ],
        "slides": [
            {"id": s.id, "label": s.label, "chapter": s.chapter}
            for s in master_deck.MANIFEST if not s.reserved
        ],
        "chapters": plan["chapters"],
        "plan": plan["slides"],
        "source": master_deck.source_info(plan["lang"]),
    }


@agent_app.get("/plan", summary="Slide-plan for en mødelængde og et sæt services")
async def agent_plan(
    lang: Optional[str] = None,
    pitch_length: str = "medium",
    services: Optional[str] = None,
):
    """Samme som `plan` i /catalogue, men uden resten: per slide `id`, `title`,
    `chapter`, `chapter_label`, `default_on`, `off_reason` (null, "length"
    eller "service"), `unlock_services`, `lengths` og `services`.
    `services` gives komma-separeret, fx `Epico Freelance,Epico Search`."""
    return _plan_payload(lang, pitch_length, services)


@agent_app.get("/slides/{slide_id}/thumbnail", summary="Miniature af en masterslide (JPEG 640x360)")
async def agent_slide_thumbnail(slide_id: str, request: Request, lang: Optional[str] = None):
    """Miniaturerne er renderet på forhånd (render_thumbs.py) og ændrer sig kun
    ved ny import, så de må caches et døgn. ETag gør gentagne hentninger til
    et 304 uden krop."""
    num = master_deck.slide_num(slide_id)
    if num is None:
        raise HTTPException(status_code=404, detail="Ukendt slide-id.")
    path = master_deck.thumb_path(num, lang)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Miniaturen findes ikke. Kør render_thumbs.py efter import.")
    data = path.read_bytes()
    etag = '"' + hashlib.sha256(data).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/jpeg", headers=headers)


@agent_app.get("/slides/{slide_id}/preview", response_class=HTMLResponse,
               summary="Én masterslide som selvstændig HTML-side")
async def agent_slide_preview(slide_id: str, lang: Optional[str] = None):
    """Sliden i fuld opløsning, skaleret til vinduets bredde, med masterens
    fonte og animationer inlinet. Til stor forhåndsvisning i Engage (iframe)."""
    num = master_deck.slide_num(slide_id)
    if num is None:
        raise HTTPException(status_code=404, detail="Ukendt slide-id.")
    lang = master_deck.resolve_lang(lang)
    if not master_deck.deck_available(lang):
        raise HTTPException(status_code=503, detail="Masterdecket er ikke indlæst.")
    html = master_deck.single_slide_html(num, lang)
    etag = '"' + hashlib.sha256(html.encode()).hexdigest()[:16] + '"'
    return HTMLResponse(html, headers={"ETag": etag, "Cache-Control": "private, max-age=3600"})


@agent_app.post("/master-deck", summary="Generér et masterdeck med kundens navn — klar med det samme")
async def agent_master_deck(req: AgentMasterDeckRequest, request: Request):
    """Den hurtige vej uden AI-research: Epicos masterpræsentation med kundens
    navn på coveret, filtreret på mødelængde og services. Svar sælgeren med
    `deck_url` som et klikbart link."""
    result = await generate_deck(GenerateDeckRequest(
        client_name=req.client_name,
        analysis={},
        meeting={"contact_person": req.contact_person or "", "date": req.date or ""},
        pitch_length=req.pitch_length or "medium",
        services=req.services,
        selected_slide_ids=req.selected_slide_ids,
        lang=req.lang,
    ))
    out = {
        "deck_url": f"{_public_base(request)}{result['url']}",
        "filename": result["filename"],
    }
    if req.include_html:
        out["html"] = result["html"]
    return out


@agent_app.post("/deck/pdf", summary="Masterdeck som PDF, én side per slide (1920x1080)")
async def agent_deck_pdf(req: AgentMasterDeckRequest):
    """Samme felter som /master-deck, men svaret er selve PDF-filen
    (application/pdf, Content-Disposition attachment). Kræver Chromium på
    serveren; mangler den, svares 503."""
    lang = master_deck.resolve_lang(req.lang)
    html = render_master_deck(
        client_name=req.client_name,
        analysis={},
        meeting={"contact_person": req.contact_person or "", "date": req.date or ""},
        pitch_length=req.pitch_length or "medium",
        services=req.services,
        selected_slide_ids=req.selected_slide_ids,
        lang=lang,
    )
    try:
        pdf = await render_pdf(master_deck.print_html(html))
    except ChromiumUnavailable:
        raise HTTPException(status_code=503, detail="PDF kræver Chromium på serveren")
    filename = f"{_safe_name(req.client_name)}-{lang}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@agent_app.post("/research", summary="Start AI-research på en kunde (tager 4-5 minutter)")
async def agent_research(req: AgentResearchRequest):
    """Starter den skræddersyede vej: CVR-opslag, web-research og AI-analyse.
    Svarer med et `job_id` med det samme. Følg fremdriften med
    GET /research/{job_id}, og kald /deck-from-research når status er 'done'.
    Skriv i `brief` hvad sælgeren ved og vil med mødet — det styrer hele pitchen."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY er ikke sat på serveren.")

    lang = master_deck.resolve_lang(req.lang)
    job_id = _new_job()
    asyncio.create_task(_do_research(
        job_id,
        client_name=req.client_name, cvr_number=req.cvr_number,
        pitch_length=req.pitch_length or "medium",
        meeting_stage=None, meeting_stakeholder=req.stakeholder,
        meeting_history=None, personal_angle=None,
        insider_insights=None, exclusions=None,
        pitch_focus=req.brief,
        services_to_highlight=",".join(req.services) if req.services else None,
        dict_research_facts=None, dict_priorities=None,
        dict_mappings=None, dict_next_steps=None,
        enable_web_search="true", enable_website_crawl="true",
        selected_slide_ids=None, lang=lang, pdf_bytes=None,
    ))
    # Gem agentens valg på jobbet, så deck-genereringen bruger samme sprog
    # og services uden at assistenten skal sende dem igen
    _RESEARCH_JOBS[job_id]["agent_params"] = {
        "lang": lang,
        "pitch_length": req.pitch_length or "medium",
        "services": req.services,
        "stakeholder": req.stakeholder,
    }
    return {"job_id": job_id, "status": "running",
            "hint": "Spørg på /research/{job_id} — typisk færdig efter 4-5 minutter."}


@agent_app.get("/research/{job_id}", summary="Status på en research-kørsel")
async def agent_research_status(job_id: str):
    """Status er 'running', 'done' eller 'error'. Ved 'done' er analysen klar,
    og decket kan genereres med /deck-from-research."""
    job = _RESEARCH_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Kørslen findes ikke. Serveren er muligvis genstartet — start research igen.")
    out = {"status": job["status"], "step": job["step"]}
    if job["status"] == "error":
        out["detail"] = job["error"]
    if job["status"] == "done":
        analysis = (job.get("result") or {}).get("analysis") or {}
        out["summary"] = {
            "client_name": (job.get("result") or {}).get("client_name"),
            "industry": analysis.get("industry_tag"),
            "research_facts": len(analysis.get("research_facts") or []),
            "value_mappings": len(analysis.get("value_mappings") or []),
            "next_steps": len(analysis.get("next_steps") or []),
        }
    return out


@agent_app.post("/deck-from-research", summary="Generér det skræddersyede deck fra en færdig research")
async def agent_deck_from_research(req: AgentDeckFromResearchRequest, request: Request):
    """Kald denne når /research/{job_id} melder status 'done'. Bygger decket
    med AI-kundeslides plus de relevante masterslides, og svarer med
    `deck_url` som sælgeren kan åbne og præsentere direkte."""
    job = _RESEARCH_JOBS.get(req.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Kørslen findes ikke. Serveren er muligvis genstartet — start research igen.")
    if job["status"] == "running":
        raise HTTPException(status_code=409, detail="Researchen kører stadig — prøv igen om lidt.")
    if job["status"] == "error":
        raise HTTPException(status_code=409, detail=f"Researchen fejlede: {job.get('error')}")

    params = job.get("agent_params") or {}
    result_data = job.get("result") or {}
    resolved = await generate_deck(GenerateDeckRequest(
        client_name=result_data.get("client_name") or "Kunden",
        analysis=result_data.get("analysis") or {},
        meeting={"contact_person": req.contact_person or ""},
        pitch_length=params.get("pitch_length") or "medium",
        services=params.get("services"),
        stakeholder=params.get("stakeholder"),
        selected_slide_ids=req.selected_slide_ids,
        lang=params.get("lang"),
    ))
    out = {
        "deck_url": f"{_public_base(request)}{resolved['url']}",
        "filename": resolved["filename"],
    }
    if req.include_html:
        out["html"] = resolved["html"]
    return out


def _agent_openapi():
    """OpenAPI-beskrivelsen Copilot Studio importerer: deklarerer API-nøglen
    som securityScheme og den offentlige server-URL, så importen kan sætte
    auth og adresse op uden håndarbejde."""
    if agent_app.openapi_schema:
        return agent_app.openapi_schema
    schema = get_openapi(
        title=agent_app.title, version=agent_app.version,
        description=agent_app.description, routes=agent_app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["ApiKey"] = {
        "type": "apiKey", "in": "header", "name": "X-Api-Key",
    }
    schema["security"] = [{"ApiKey": []}]
    env = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if env:
        base = env if env.startswith("http") else f"https://{env}"
        schema["servers"] = [{"url": f"{base}/agent"}]
    agent_app.openapi_schema = schema
    return schema


agent_app.openapi = _agent_openapi
app.mount("/agent", agent_app)


if __name__ == "__main__":
    import uvicorn
    # Railway sætter $PORT — lokalt bruger vi 8000.
    # Railway kører normalt via Procfile, men dette er fallback.
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run("main:app", host=host, port=port, reload=False)
