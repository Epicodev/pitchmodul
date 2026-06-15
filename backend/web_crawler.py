"""
Website-crawler. Henter de mest informative sider på en virksomheds hjemmeside.

Strategi:
1. Hent forside → udtræk navigation-links
2. Identificer "om os", "strategi", "investor", "karriere"-sider
3. Hent op til N sider og uddrag ren tekst-indhold
4. Returnér konsolideret tekst klar til Claude
"""
import re
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup


USER_AGENT = "Epico-Pitch-Composer/1.0 (https://epico.dk)"
TIMEOUT = 15.0
MAX_PAGES = 8
MAX_CHARS_PER_PAGE = 8000


# Keyword-mønstre der angiver "værdifulde" sider
# Rangeret efter prioritet (først = mest værdifulde)
PRIORITY_PATTERNS = [
    # Højeste prioritet — strategi og finansielt
    (r"strateg|vision|mission|purpose|about[\-/_]?us|om[\-/_]?os", 10),
    (r"investor|annual[\-/_]?report|årsrapport|earnings|financ", 9),
    (r"sustainability|esg|ansvar|csr", 8),
    (r"news|nyheder|press|presse|media|insights", 7),
    (r"leadership|management|ledelse|board|bestyrelse|team", 6),
    (r"career|karriere|jobs?|talent", 5),
    (r"product|services|løsninger|solutions", 4),
    (r"customer|case|reference", 3),
]


def _score_url(url: str, link_text: str = "") -> int:
    """Score en URL baseret på hvor sandsynligt den er at indeholde værdifuld info."""
    haystack = (url + " " + link_text).lower()
    for pattern, score in PRIORITY_PATTERNS:
        if re.search(pattern, haystack):
            return score
    return 0


def _is_same_domain(url: str, base_domain: str) -> bool:
    try:
        return urlparse(url).netloc.replace("www.", "") == base_domain
    except Exception:
        return False


def _extract_text(html: str) -> str:
    """Uddrag ren tekst fra HTML. Fjern script/style/nav/footer-junk."""
    soup = BeautifulSoup(html, "lxml")

    # Fjern junk
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "img", "video", "audio"]):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": "navigation"}):
        tag.decompose()

    # Saml meningsfuld tekst — prioritér main/article/section
    main = soup.find("main") or soup.find("article") or soup.find("body")
    if not main:
        return ""

    # Saml tekst — bevarer overskrifter som markeringer
    parts = []
    for el in main.descendants:
        if el.name in ("h1", "h2", "h3"):
            text = el.get_text(strip=True)
            if text:
                parts.append(f"\n## {text}\n")
        elif el.name in ("h4", "h5", "h6"):
            text = el.get_text(strip=True)
            if text:
                parts.append(f"\n### {text}\n")
        elif el.name == "p":
            text = el.get_text(strip=True)
            if text and len(text) > 20:  # Filtrér meget korte fragmenter
                parts.append(text)
        elif el.name == "li":
            text = el.get_text(strip=True)
            if text and len(text) > 10:
                parts.append(f"- {text}")

    text = "\n".join(parts)
    # Komprimér multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_CHARS_PER_PAGE]


def _find_priority_links(base_url: str, html: str) -> List[Tuple[str, int, str]]:
    """
    Find de højest scorende interne links på forsiden.
    Returnerer liste af (absolut_url, score, link_tekst), sorteret efter score.
    """
    base_domain = urlparse(base_url).netloc.replace("www.", "")
    soup = BeautifulSoup(html, "lxml")

    seen = set()
    scored = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        absolute = urljoin(base_url, href)
        if not _is_same_domain(absolute, base_domain):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)

        link_text = a.get_text(strip=True)[:80]
        score = _score_url(absolute, link_text)
        if score > 0:
            scored.append((absolute, score, link_text))

    # Sortér efter score, derefter alfabetisk for stabilitet
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


async def crawl(website_url: str, max_pages: int = MAX_PAGES) -> Dict[str, str]:
    """
    Crawl en virksomheds hjemmeside og uddrag ren tekst fra de mest værdifulde sider.

    Args:
        website_url: Forside-URL (med eller uden https://)
        max_pages: Maks. antal sider at hente udover forsiden

    Returnerer:
        {
            "homepage_url": "https://...",
            "pages": [
                {"url": "...", "title": "...", "score": 10, "text": "..."},
                ...
            ],
            "consolidated_text": "Sammenfattet tekst fra alle sider"
        }
    """
    # Normalisér URL
    if not website_url.startswith("http"):
        website_url = "https://" + website_url
    website_url = website_url.rstrip("/")

    result = {
        "homepage_url": website_url,
        "pages": [],
        "consolidated_text": "",
        "error": None,
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        # 1. Hent forsiden
        try:
            resp = await client.get(website_url)
            resp.raise_for_status()
        except Exception as e:
            result["error"] = f"Kunne ikke hente forsiden: {e}"
            return result

        homepage_html = resp.text
        homepage_text = _extract_text(homepage_html)
        soup = BeautifulSoup(homepage_html, "lxml")
        homepage_title = soup.title.string.strip() if soup.title and soup.title.string else website_url

        result["pages"].append({
            "url": str(resp.url),
            "title": homepage_title,
            "score": 100,
            "text": homepage_text,
        })

        # 2. Find priority-links
        priority_links = _find_priority_links(str(resp.url), homepage_html)

        # 3. Hent de N højest-scorende links
        seen_urls = {str(resp.url)}
        for absolute_url, score, link_text in priority_links[:max_pages]:
            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)

            try:
                page_resp = await client.get(absolute_url)
                if page_resp.status_code != 200:
                    continue
                page_text = _extract_text(page_resp.text)
                if len(page_text) < 200:
                    continue  # Skip meget tomme sider

                page_soup = BeautifulSoup(page_resp.text, "lxml")
                page_title = page_soup.title.string.strip() if page_soup.title and page_soup.title.string else link_text

                result["pages"].append({
                    "url": str(page_resp.url),
                    "title": page_title,
                    "score": score,
                    "text": page_text,
                })
            except Exception:
                continue  # Skip enkelte fejlede sider

        # 4. Konsoliderede tekst
        consolidated = []
        for page in result["pages"]:
            consolidated.append(f"### {page['title']}\n[Kilde: {page['url']}]\n\n{page['text']}")
        result["consolidated_text"] = "\n\n---\n\n".join(consolidated)

    return result


if __name__ == "__main__":
    import asyncio
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://epicogroup.com"
    print(f"Crawling: {url}\n")
    data = asyncio.run(crawl(url))
    print(f"Pages found: {len(data['pages'])}")
    for p in data["pages"]:
        print(f"  [{p['score']:3d}] {p['title'][:60]} — {p['url']}")
    print(f"\nTotal text: {len(data['consolidated_text'])} chars")
    print(f"\n--- First 1500 chars ---\n{data['consolidated_text'][:1500]}")
