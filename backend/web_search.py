"""
Web search via Anthropic's indbyggede web_search tool.

Lader Claude søge efter:
- Aktuelle pressemeddelelser
- Nyheder om virksomheden
- Strategi-rapporter / interviews
- Jobopslag (signal om vækst-områder)
- Finansielle resultater (hvis ikke i årsrapport)
"""
import os
from typing import Optional, Dict, Any, List
from anthropic import Anthropic


SEARCH_MODEL = "claude-sonnet-4-6"


def gather_web_intelligence(
    client_name: str,
    industry_hint: Optional[str] = None,
    pitch_focus: Optional[str] = None,
    max_searches: int = 5,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Kør Claude med web_search tool til at indsamle aktuel intelligens om kunden.

    Returnerer:
        {
            "summary": "Strikt opsummering af hvad der blev fundet",
            "raw_findings": [{"title": ..., "url": ..., "snippet": ...}, ...],
            "search_count": int (hvor mange søgninger Claude udførte),
        }
    """
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    # Byg fokuseret prompt
    focus_hint = f"\n\nSælgers pitch-fokus: {pitch_focus}" if pitch_focus else ""
    industry_line = f" (branche: {industry_hint})" if industry_hint else ""

    prompt = f"""Du er research-assistent for en Epico-sælger der skal pitche til **{client_name}**{industry_line}.

Brug web_search til at finde de mest værdifulde, AKTUELLE oplysninger om denne kunde der kan bruges i en pitch. Fokusér på:

1. **Pressemeddelelser** fra sidste 12 måneder (især om strategi, ekspansion, ledelsesændringer, store IT-projekter)
2. **Nyheder** om virksomheden — særligt udfordringer eller transformations-initiativer
3. **Aktuelle jobopslag** (signal om hvor de skalerer / hvilke kompetencer de mangler)
4. **Strategi-erklæringer** fra CEO eller bestyrelse (interviews, podcasts)
5. **Finansielle højdepunkter** (hvis offentligt tilgængeligt)

Begræns dig til max {max_searches} søgninger. Vælg dem klogt — kvalitet over kvantitet.{focus_hint}

Når du har samlet info, returnér en **STRUKTURERET OPSUMMERING** på dansk i dette format:

```
## Aktuelle nyheder & pressemeddelelser
- [Headline] (kilde, dato): kort opsummering
- ...

## Strategiske initiativer
- [Initiativ] (kilde): hvad de gør, hvorfor det er relevant for pitchen
- ...

## Vækst-signaler (jobopslag, ekspansion)
- [Signal]: hvad det fortæller os
- ...

## Ledelse & nøglepersoner (hvis relevant)
- [Navn, rolle]: kilde

## Top 5 fakta sælgeren BØR vide før mødet
1. ...
2. ...
3. ...
4. ...
5. ...
```

Brug KUN information du har verificeret via web search. **Find ikke noget på.** Hvis en kategori er tom — skriv "Intet relevant fundet".
"""

    try:
        response = client.messages.create(
            model=SEARCH_MODEL,
            max_tokens=4000,
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": max_searches,
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )

        # Uddrag text response
        summary_parts = []
        search_count = 0
        for block in response.content:
            if block.type == "text":
                summary_parts.append(block.text)
            elif block.type == "server_tool_use":
                search_count += 1

        summary = "\n".join(summary_parts).strip()

        return {
            "summary": summary,
            "search_count": search_count,
            "stop_reason": response.stop_reason,
        }

    except Exception as e:
        # Web search kan fejle hvis API-key ikke har adgang, eller andre fejl
        # Vi vil ikke crashe hele pipeline pga. dette
        return {
            "summary": None,
            "search_count": 0,
            "error": str(e),
        }


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "LEGO Group"
    print(f"Søger om: {name}\n")
    result = gather_web_intelligence(name, industry_hint="Legetøj/Industri")
    if result.get("error"):
        print(f"FEJL: {result['error']}")
    else:
        print(f"Søgninger udført: {result['search_count']}")
        print(f"\n{result['summary'][:3000]}")
