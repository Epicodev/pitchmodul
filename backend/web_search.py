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
    research_queries: Optional[List[str]] = None,
    core_intent: Optional[str] = None,
    max_searches: int = 5,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Kør Claude med web_search tool til at indsamle aktuel intelligens om kunden.

    Hvis `research_queries` er givet (fra pitch-kontrakten), søger vi MÅLRETTET efter
    dét sælgeren skal tale om — i stedet for at støvsuge generisk firmanyt. Samme
    antal søgninger, men rettet mod det der faktisk skal bruges.

    Returnerer:
        {
            "summary": "Strikt opsummering af hvad der blev fundet",
            "raw_findings": [{"title": ..., "url": ..., "snippet": ...}, ...],
            "search_count": int (hvor mange søgninger Claude udførte),
        }
    """
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    industry_line = f" (branche: {industry_hint})" if industry_hint else ""

    # MÅLRETTET tilstand: pitch-kontrakten har fortalt os hvad mødet handler om,
    # så vi søger efter dét — ikke efter generisk firmanyt.
    if research_queries:
        intent_line = f"\n\n**Hvad mødet handler om**: {core_intent}" if core_intent else ""
        queries_block = "\n".join(f"{i}. {q}" for i, q in enumerate(research_queries, 1))
        brief_block = f"""Du er research-assistent for en Epico-sælger der skal pitche til **{client_name}**{industry_line}.{intent_line}

Sælgeren har allerede besluttet hvad mødet skal handle om. Din opgave er **ikke** at kortlægge
virksomheden bredt — det er at finde belæg for netop disse spørgsmål:

{queries_block}

Brug web_search målrettet mod dem. Max {max_searches} søgninger — brug dem alle på listen ovenfor,
ikke på generisk baggrund. Er et spørgsmål udtømt efter én søgning, gå videre til det næste
frem for at grave dybere i samme.

Finder du noget stort og relevant der IKKE står på listen, må du tage det med — men kun hvis det
ændrer billedet, ikke bare fordi det er interessant."""
        output_spec = """

Returnér en **STRUKTURERET OPSUMMERING** på dansk, organiseret efter spørgsmålene ovenfor:

```
## Spørgsmål 1: [gentag spørgsmålet kort]
- [Fund] (kilde, dato): hvad vi fandt
- **Svar**: dit direkte svar på spørgsmålet, eller "Intet belæg fundet"

## Spørgsmål 2: ...
(samme struktur for hvert spørgsmål)

## Uventede fund
- Kun ting der ændrer billedet. Tom hvis intet.

## Det sælgeren BØR vide før mødet
1. ...
2. ...
3. ...
```
"""
        prompt = brief_block + output_spec + """
Brug KUN information du har verificeret via web search. **Find ikke noget på.**
Et ærligt "Intet belæg fundet" er mere værd end et kvalificeret gæt."""

        return _run_search(client, prompt, max_searches)

    # BRED tilstand: ingen kontrakt endnu — kortlæg virksomheden generisk.
    focus_hint = f"\n\nSælgers pitch-fokus: {pitch_focus}" if pitch_focus else ""

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

    return _run_search(client, prompt, max_searches)


def _run_search(client: Anthropic, prompt: str, max_searches: int) -> Dict[str, Any]:
    """Kør ét web-search-kald og pak resultatet ud. Fejler stille."""
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

        summary_parts = []
        search_count = 0
        for block in response.content:
            if block.type == "text":
                summary_parts.append(block.text)
            elif block.type == "server_tool_use":
                search_count += 1

        return {
            "summary": "\n".join(summary_parts).strip(),
            "search_count": search_count,
            "stop_reason": response.stop_reason,
        }

    except Exception as e:
        # Web search kan fejle hvis API-key ikke har adgang. Ikke kritisk —
        # pipelinen kører videre uden.
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
