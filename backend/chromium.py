"""Rendering med Chromium via Playwright: miniaturer og PDF.

Playwright importeres dovent inde i funktionerne. Serveren skal kunne starte
uden Chromium (PDF svarer saa 503), og import_master.py skal kunne koere paa
en maskine uden browser og bare springe miniaturerne over.

Deploy: Dockerfile i roden bygger paa Microsofts Playwright-image, saa
Chromium og systembiblioteker foelger med. Lokalt: se README/DEPLOY.md.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Tuple

THUMB_WIDTH = 640
THUMB_HEIGHT = 360
THUMB_QUALITY = 80

PDF_WIDTH = "1920px"
PDF_HEIGHT = "1080px"


class ChromiumUnavailable(RuntimeError):
    """Playwright er ikke installeret, eller Chromium mangler paa maskinen."""


def _launch_args() -> list:
    # Chromium naegter at koere som root uden sandbox-flaget. I Docker-imaget
    # koerer processen som root, lokalt beholder vi sandboxen.
    if getattr(os, "geteuid", lambda: 1)() == 0:
        return ["--no-sandbox", "--disable-dev-shm-usage"]
    return []


def render_thumbnails_sync(jobs: Iterable[Tuple[Path, str]]) -> int:
    """Gem et 640x360 JPEG per (sti, html) i én browsersession.

    Siden bygges saa .stage skaleres til vinduets bredde (single_slide_html),
    saa et viewport paa 640x360 giver praecis miniaturens stoerrelse.
    Synkron API, fordi den kaldes fra kommandolinjen (render_thumbs.py og
    import_master.py), ikke fra serveren.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ChromiumUnavailable("Playwright er ikke installeret (pip install playwright).") from e

    count = 0
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=_launch_args())
        except Exception as e:  # Executable doesn't exist o.l.
            raise ChromiumUnavailable(f"Chromium kunne ikke startes: {e}") from e
        try:
            page = browser.new_page(
                viewport={"width": THUMB_WIDTH, "height": THUMB_HEIGHT},
                device_scale_factor=1,
            )
            for out_path, html in jobs:
                page.set_content(html, wait_until="load")
                page.evaluate("document.fonts.ready")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(out_path), type="jpeg", quality=THUMB_QUALITY,
                    clip={"x": 0, "y": 0, "width": THUMB_WIDTH, "height": THUMB_HEIGHT},
                )
                count += 1
        finally:
            browser.close()
    return count


async def render_pdf(html: str) -> bytes:
    """Print et dokument (master_deck.print_html) til PDF, én side per slide.

    Async, fordi den kaldes fra FastAPI. Sidestoerrelsen er 1920x1080 px, saa
    hver .page i dokumentet fylder praecis én PDF-side.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise ChromiumUnavailable("Playwright er ikke installeret (pip install playwright).") from e

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(args=_launch_args())
        except Exception as e:
            raise ChromiumUnavailable(f"Chromium kunne ikke startes: {e}") from e
        try:
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            # Skaermmedie, saa decket ser ud som i browseren; @page gaelder alligevel.
            await page.emulate_media(media="screen")
            await page.set_content(html, wait_until="load")
            await page.evaluate("document.fonts.ready")
            return await page.pdf(
                width=PDF_WIDTH, height=PDF_HEIGHT,
                print_background=True, prefer_css_page_size=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            await browser.close()
