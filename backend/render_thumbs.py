"""Render miniaturer af masterdeckets slides med Chromium.

Hver slide i master_deck/{lang}/slides/ bliver til et JPEG paa 640x360
(kvalitet 80) i master_deck/{lang}/thumbs/mNN.jpg. Miniaturerne committes,
fordi masterfilen aendrer sig sjaeldent, og serveren skal ikke have Chromium
for at servere dem (GET /agent/slides/{id}/thumbnail).

Brug:  python render_thumbs.py            (alle importerede sprog)
       python render_thumbs.py --lang=da  (ét sprog)

Kraever Playwright med Chromium:
    pip install playwright && playwright install chromium

import_master.py kalder render_thumbs() automatisk efter en import.
"""
from __future__ import annotations

import sys
from pathlib import Path

import master_deck
from chromium import ChromiumUnavailable, render_thumbnails_sync


def render_thumbs(lang: str) -> int:
    """Render alle slides for ét sprog. Returnerer antal skrevne filer."""
    lang = master_deck.resolve_lang(lang)
    if not master_deck.deck_available(lang):
        raise SystemExit(f"Masterdecket er ikke importeret for '{lang}'.")

    slides = master_deck._load(lang)["slides"]
    thumbs_dir = master_deck.lang_dir(lang) / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    for old in thumbs_dir.glob("*.jpg"):
        old.unlink()

    jobs = (
        (master_deck.thumb_path(num, lang), master_deck.single_slide_html(num, lang, freeze=True))
        for num in sorted(slides)
    )
    return render_thumbnails_sync(jobs)


if __name__ == "__main__":
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    wanted = next((f.split("=", 1)[1] for f in flags if f.startswith("--lang=")), None)
    langs = [wanted] if wanted else master_deck.available_languages()
    if not langs:
        print("Ingen masterdeck importeret. Koer import_master.py foerst.")
        sys.exit(1)

    for lang in langs:
        try:
            n = render_thumbs(lang)
        except ChromiumUnavailable as e:
            print(f"Kunne ikke rendere miniaturer: {e}")
            sys.exit(2)
        out = Path("master_deck") / lang / "thumbs"
        print(f"{lang}: {n} miniaturer skrevet til {out}/")
