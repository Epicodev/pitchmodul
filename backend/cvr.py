"""
CVR-API client til at hente grunddata om danske virksomheder.
Bruger det åbne CVR-API på cvrapi.dk (ingen API-key krævet for lav volumen).
"""
import httpx
from typing import Optional, Dict, Any


CVR_API_BASE = "https://cvrapi.dk/api"
USER_AGENT = "Epico-Pitch-Deck-Generator/1.0 (https://epico.dk)"


async def lookup_by_name(name: str, country: str = "dk") -> Optional[Dict[str, Any]]:
    """
    Find en virksomhed ud fra navn. Returnerer rigeste match.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                CVR_API_BASE,
                params={"search": name, "country": country},
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            # cvrapi.dk returnerer enten et enkelt objekt eller en error
            if isinstance(data, dict) and data.get("error"):
                return None
            return _normalize(data) if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None


async def lookup_by_cvr(cvr_number: str, country: str = "dk") -> Optional[Dict[str, Any]]:
    """
    Find en virksomhed ud fra CVR-nummer.
    """
    cvr_clean = str(cvr_number).replace(" ", "").replace("-", "")
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                CVR_API_BASE,
                params={"search": cvr_clean, "country": country},
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                return None
            return _normalize(data) if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliserer CVR-data til en strømlinet struktur.
    """
    address_parts = []
    if raw.get("address"):
        address_parts.append(raw["address"])
    if raw.get("zipcode"):
        address_parts.append(str(raw["zipcode"]))
    if raw.get("city"):
        address_parts.append(raw["city"])
    address = ", ".join(address_parts) if address_parts else None

    # Seneste regnskab
    latest_year = None
    revenue = None
    profit = None
    employees = None

    if raw.get("productionunits"):
        # employees fra produktionsenheder
        for unit in raw["productionunits"]:
            if unit.get("employees"):
                employees = unit["employees"]
                break

    if not employees:
        employees = raw.get("employees")

    return {
        "name": raw.get("name"),
        "cvr": raw.get("vat") or raw.get("cvr"),
        "industry_code": raw.get("industrycode"),
        "industry_desc": raw.get("industrydesc"),
        "address": address,
        "phone": raw.get("phone"),
        "email": raw.get("email"),
        "website": raw.get("website"),
        "employees": employees,
        "company_type": raw.get("companydesc"),
        "founded": raw.get("startdate"),
        "owner_name": raw.get("owners")[0].get("name") if raw.get("owners") else None,
        "raw": raw,  # Behold rådata for debugging
    }
