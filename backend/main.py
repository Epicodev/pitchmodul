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
import re
import json
import hashlib
import time
import uuid
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
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
    _strip_long_dashes,
)
import master_deck
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

    # Gem til disk — sproget med i navnet, så et DA- og EN-deck genereret i
    # samme sekund ikke overskriver hinanden
    safe_name = "".join(c if c.isalnum() else "_" for c in req.client_name).lower()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"{safe_name}-{lang}-{timestamp}.html"
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
