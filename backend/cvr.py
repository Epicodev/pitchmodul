"""
CVR-API client til at hente grunddata om danske virksomheder.
Bruger det åbne CVR-API på cvrapi.dk (ingen API-key krævet for lav volumen).
"""
import httpx
from typing import Optional, Dict, Any


CVR_API_BASE = "https://cvrapi.dk/api"
USER_AGENT = "Epico-Pitch-Deck-Generator/1.0 (https://epico.dk)"


class CVRUnavailable(Exception):
    """API'et svarede, men kunne ikke slå op — kvote opbrugt eller nede.

    Adskilt fra "virksomheden findes ikke", fordi de to kræver hver sin
    handling af sælgeren: vent kontra tjek stavemåden.
    """


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
            data = _parse(resp)
            return _normalize(data) if data else None
        except (httpx.HTTPError, ValueError):
            raise CVRUnavailable("CVR-registret svarede ikke")


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
            data = _parse(resp)
            return _normalize(data) if data else None
        except (httpx.HTTPError, ValueError):
            raise CVRUnavailable("CVR-registret svarede ikke")


def _parse(resp: "httpx.Response") -> Optional[Dict[str, Any]]:
    """Pak et cvrapi.dk-svar ud. Returnerer None hvis virksomheden ikke findes;
    kaster CVRUnavailable hvis selve tjenesten ikke kan svare lige nu."""
    if resp.status_code in (429, 402, 403):
        raise CVRUnavailable("CVR-registrets gratiskvote er brugt op")
    if resp.status_code >= 500:
        raise CVRUnavailable("CVR-registret er nede lige nu")
    if resp.status_code != 200:
        return None

    data = resp.json()
    if not isinstance(data, dict):
        return None

    error = data.get("error")
    if error:
        # cvrapi.dk svarer 200 med en error-nøgle når kvoten er opbrugt
        if error in ("QUOTA_EXCEEDED", "RATE_LIMIT"):
            raise CVRUnavailable("CVR-registrets gratiskvote er brugt op")
        return None

    return data


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
