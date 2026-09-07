"""Rezepte Import – optionale Erweiterung fuer ha-rezepte."""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DOMAIN                    = "rezepte_import"
REZEPTE_DOMAIN            = "rezepte"
RESULT_FILE               = "import_result.json"
AGENT_ID_DEFAULT          = "conversation.google_generative_ai"
LLMVISION_PROVIDER_DEFAULT = "Google"
MAX_TEXT_LENGTH           = 8000
VALID_UNITS               = {"g", "kg", "ml", "l", "TL", "EL", "Stk.", "Prise", "n.B."}

_PROMPT_BASE = """Du bist ein Rezept-Extraktor. Antworte IMMER nur mit einem validen JSON-Objekt.
Kein Text davor oder danach, kein Markdown, keine Erklaerung – nur JSON.
Auch wenn der Inhalt unleserlich wirkt: gib trotzdem JSON zurueck.

Format:
{
  "title": "Rezeptname",
  "subtitle": "Geraetename oder Variante (leer wenn nicht vorhanden)",
  "emoji": "passendes Emoji",
  "category": "Kategorie",
  "description": "1-2 Saetze Kurzbeschreibung",
  "baseServings": 4,
  "servingLabel": "Portionen",
  "ingredients": [{"amount": 200, "unit": "g", "name": "Zutatname"}],
  "steps": [{"text": "Schrittbeschreibung", "timerSec": 300, "airfryerTemp": 0, "airfryerTime": 0}],
  "notes": ["Tipp"]
}

Regeln: amount=Zahl, unit eines von: g kg ml l TL EL Stk. Prise n.B.
timerSec=Sekunden (0 wenn kein Timer). Kein Rezept erkennbar: title="Kein Rezept erkannt" ingredients=[] steps=[].
airfryerTemp=Airfryer-Temperatur in Grad Celsius (0 wenn Schritt keine Airfryer-Temperaturangabe enthaelt).
airfryerTime=Airfryer-Zeit in Minuten (0 wenn Schritt keine Airfryer-Zeitangabe enthaelt).
Setze airfryerTemp/airfryerTime NUR wenn der Schritt explizit Heissluftfritteuse/Airfryer erwaehnt
oder das Rezept eindeutig ein Airfryer-Rezept ist (z. B. Geraetename im subtitle enthaelt "Airfryer"/"Heissluftfritteuse").
WICHTIG fuer steps.text: KEINE Mengenangaben in den Schritten (keine Zahlen wie "200g" oder "3 EL").
Verwende stattdessen nur Bezeichnungen wie "das Mehl", "die Butter", "das Oel".
Die Mengen stehen bereits in der Zutatenliste und werden automatisch skaliert.
ANTWORTE NUR MIT JSON.

Rezepttext:
"""

_PROMPT_IMAGE = """Du bist ein Rezept-Extraktor. Analysiere das Bild und gib AUSSCHLIESSLICH ein JSON-Objekt zurueck.
Kein Text, kein Markdown – nur JSON.

Format:
{
  "title": "Rezeptname",
  "subtitle": "",
  "emoji": "passendes Emoji",
  "category": "Kategorie",
  "description": "Kurzbeschreibung",
  "baseServings": 4,
  "servingLabel": "Portionen",
  "ingredients": [{"amount": 200, "unit": "g", "name": "Zutatname"}],
  "steps": [{"text": "Schrittbeschreibung", "timerSec": 0, "airfryerTemp": 0, "airfryerTime": 0}],
  "notes": []
}

Regeln: amount=Zahl, unit eines von: g kg ml l TL EL Stk. Prise n.B., timerSec=Sekunden.
airfryerTemp=Airfryer-Temperatur in Grad Celsius, airfryerTime=Airfryer-Zeit in Minuten
(beide 0 wenn kein Airfryer-Rezept bzw. Schritt keine Angabe enthaelt).
ANTWORTE NUR MIT JSON."""



def _get_prompt(entry_data: dict) -> str:
    """Aktiven Prompt aus Konfiguration lesen."""
    if entry_data.get("prompt_mode") == "custom":
        custom = entry_data.get("custom_prompt", "").strip()
        if custom:
            return custom + "\n\nRezepttext:\n"
    return _PROMPT_BASE


def _get_image_prompt(entry_data: dict) -> str:
    """Aktiven Bild-Prompt aus Konfiguration lesen."""
    if entry_data.get("image_prompt_mode") == "custom":
        custom = entry_data.get("custom_image_prompt", "").strip()
        if custom:
            return custom
    return _PROMPT_IMAGE

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Services einrichten."""
    agent_id       = entry.data.get("conversation_agent", AGENT_ID_DEFAULT)
    llmvision_prov = entry.data.get("llmvision_provider", LLMVISION_PROVIDER_DEFAULT)
    prompt_base    = _get_prompt(entry.data)
    image_prompt   = _get_image_prompt(entry.data)
    vision_api_key = entry.data.get("vision_api_key", "").strip()
    vision_model   = entry.data.get("vision_model", "meta-llama/llama-4-maverick-17b-128e-instruct").strip()

    # ── parse_text ────────────────────────────────────────────────────────────
    async def handle_parse_text(call: ServiceCall) -> None:
        text = call.data.get("text", "").strip()
        if not text:
            await _write_error(hass, "Kein Text uebergeben.")
            return
        await _call_conversation(hass, agent_id, prompt_base + text)

    # ── parse_image ───────────────────────────────────────────────────────────
    async def handle_parse_image(call: ServiceCall) -> None:
        image_b64 = call.data.get("image_data", "")
        mime_type  = call.data.get("mime_type", "image/jpeg")
        if not image_b64:
            await _write_error(hass, "Keine Bilddaten uebergeben.")
            return
        ext      = "jpg" if "jpeg" in mime_type else mime_type.split("/")[-1]
        tmp_path = f"/tmp/rezept_import_{int(time.time())}.{ext}"
        await hass.async_add_executor_job(_write_image_file, tmp_path, image_b64)
        try:
            response_text = await _analyze_image(hass, tmp_path, llmvision_prov, image_prompt, vision_api_key, vision_model)
            await _write_parsed(hass, response_text)
        except Exception as err:
            await _write_error(hass, f"Bilderkennung fehlgeschlagen: {err}")
        finally:
            await hass.async_add_executor_job(_delete_file, tmp_path)

    # ── parse_url ─────────────────────────────────────────────────────────────
    async def handle_parse_url(call: ServiceCall) -> None:
        url = call.data.get("url", "").strip()
        if not url:
            await _write_error(hass, "Keine URL uebergeben.")
            return
        try:
            session = async_get_clientsession(hass)
            import aiohttp
            async with session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; HA-Rezepte-Import/1.0)"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                html = await resp.text(errors="replace")
        except Exception as err:
            await _write_error(hass, f"URL abrufen fehlgeschlagen: {err}")
            return

        # JSON-LD zuerst versuchen (strukturierte Rezeptdaten vieler Rezeptseiten)
        jsonld = _extract_jsonld_recipe(html)
        if jsonld:
            text = f"Strukturierte Rezeptdaten (JSON-LD):\n{jsonld}"
        else:
            text = _extract_text_from_html(html)[:MAX_TEXT_LENGTH]

        await _call_conversation(hass, agent_id, prompt_base + text)

    # ── parse_pdf ──────────────────────────────────────────────────────────────
    async def handle_parse_pdf(call: ServiceCall) -> None:
        pdf_b64 = call.data.get("pdf_data", "")
        if not pdf_b64:
            await _write_error(hass, "Keine PDF-Daten uebergeben.")
            return
        # Text extrahieren (Executor-Thread, da synchrone pypdf-Operation)
        try:
            text = await hass.async_add_executor_job(_extract_pdf_text, pdf_b64)
        except Exception as err:
            await _write_error(hass, f"PDF-Verarbeitung fehlgeschlagen: {err}")
            return
        if not text.strip():
            # Kein Text → gescanntes PDF → Fallback: erste Seite via Groq Vision
            if not vision_api_key:
                await _write_error(
                    hass,
                    "Kein Text im PDF gefunden (gescanntes PDF). "
                    "Tipp: Groq API-Key in der Konfiguration eintragen "
                    "um gescannte PDFs automatisch zu verarbeiten. "
                    "Alternativ: Google Lens → Text-Tab.",
                )
                return
            _LOGGER.debug("PDF ohne Text – versuche Groq Vision Fallback (pypdf Bildextraktion)")
            try:
                img_b64, _mime = await hass.async_add_executor_job(
                    _pdf_page_to_image, pdf_b64
                )
            except Exception as err:
                await _write_error(hass, f"PDF→Bild Konvertierung fehlgeschlagen: {err}")
                return
            tmp_path = f"/tmp/rezept_pdf_page_{int(time.time())}.jpg"
            await hass.async_add_executor_job(_write_image_file, tmp_path, img_b64)
            try:
                response_text = await _analyze_image(
                    hass, tmp_path, llmvision_prov,
                    image_prompt, vision_api_key, vision_model,
                )
                await _write_parsed(hass, response_text)
            except Exception as err:
                await _write_error(hass, f"Gescanntes PDF – Bildanalyse fehlgeschlagen: {err}")
            finally:
                await hass.async_add_executor_job(_delete_file, tmp_path)
            return
        _LOGGER.debug("PDF: %d Zeichen Text extrahiert", len(text))
        await _call_conversation(hass, agent_id, prompt_base + text[:MAX_TEXT_LENGTH])

    hass.services.async_register(DOMAIN, "parse_text",  handle_parse_text)
    hass.services.async_register(DOMAIN, "parse_image", handle_parse_image)
    hass.services.async_register(DOMAIN, "parse_url",   handle_parse_url)
    hass.services.async_register(DOMAIN, "parse_pdf",   handle_parse_pdf)

    _LOGGER.info("Rezepte Import geladen (Agent: %s, Vision: %s)", agent_id, llmvision_prov)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    for svc in ("parse_text", "parse_image", "parse_url", "parse_pdf"):
        hass.services.async_remove(DOMAIN, svc)
    return True


# ── KI-Aufruf ─────────────────────────────────────────────────────────────────


async def _analyze_image(
    hass: HomeAssistant,
    image_path: str,
    llmvision_prov: str = "Google",
    image_prompt: str = _PROMPT_IMAGE,
    vision_api_key: str = "",
    vision_model: str = "meta-llama/llama-4-maverick-17b-128e-instruct",
) -> str:
    """Bild analysieren.

    Reihenfolge:
    1. Direkter OpenAI-kompatibler Vision-API-Aufruf (wenn API-Key vorhanden)
    2. LLM Vision (Fallback)
    """
    import base64
    import aiohttp as _aiohttp

    errors: list[str] = []

    # ── 1. Direkte Vision API (Groq oder OpenAI-kompatibel) ──────────────────
    if vision_api_key:
        try:
            # Bild als base64 lesen (im Executor-Thread)
            def _read_b64() -> tuple[str, str]:
                ext = image_path.lower().rsplit(".", 1)[-1]
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
                with open(image_path, "rb") as fh:
                    return base64.b64encode(fh.read()).decode(), mime

            b64, mime = await hass.async_add_executor_job(_read_b64)

            # Endpoint: Groq Standard, kann per vision_model-Praefix ueberschrieben werden
            endpoint = "https://api.groq.com/openai/v1/chat/completions"

            session = async_get_clientsession(hass)
            async with session.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {vision_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": vision_model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": image_prompt},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{mime};base64,{b64}"
                            }},
                        ],
                    }],
                    "max_tokens": 8192,
                },
                timeout=_aiohttp.ClientTimeout(total=60),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                text = data["choices"][0]["message"]["content"]
                if text:
                    _LOGGER.debug("Bild analysiert via direkter Vision API (%s)", vision_model)
                    return str(text)
                errors.append("Vision API: leere Antwort")
        except Exception as err:
            errors.append(f"Vision API ({vision_model}): {err}")
            _LOGGER.warning("Direkte Vision API fehlgeschlagen: %s", err)

    # ── 2. LLM Vision Fallback ────────────────────────────────────────────────
    try:
        result = await hass.services.async_call(
            "llmvision", "image_analyzer",
            {
                "provider":         llmvision_prov,
                "message":          image_prompt,
                "image_file":       [image_path],
                "max_tokens":       8192,
                "target_width":     1920,
                "include_filename": False,
            },
            blocking=True,
            return_response=True,
        )
        text = result.get("response_text", "")
        if isinstance(text, list):
            text = "\n".join(
                x.get("text", str(x)) if isinstance(x, dict) else str(x)
                for x in text
            )
        if text:
            _LOGGER.debug("Bild analysiert via LLM Vision (%s)", llmvision_prov)
            return str(text)
        errors.append(f"LLM Vision ({llmvision_prov}): leere Antwort")
    except Exception as err:
        errors.append(f"LLM Vision ({llmvision_prov}): {err}")
        _LOGGER.debug("LLM Vision fehlgeschlagen: %s", err)

    raise RuntimeError(
        "Kein Bildanalyse-Dienst verfuegbar. "
        "Tipp: Groq API-Key in der Integration konfigurieren. "
        f"Fehler: {'; '.join(errors)}"
    )

async def _call_conversation(hass: HomeAssistant, agent_id: str, prompt: str) -> None:
    try:
        result = await hass.services.async_call(
            "conversation", "process",
            {"text": prompt, "agent_id": agent_id, "language": "de"},
            blocking=True,
            return_response=True,
        )
        response_text = (
            result
            .get("response", {})
            .get("speech", {})
            .get("plain", {})
            .get("speech", "")
        )
        await _write_parsed(hass, response_text)
    except Exception as err:
        await _write_error(hass, f"Konversations-API Fehler: {err}")


async def _write_parsed(hass: HomeAssistant, response_text: str) -> None:
    if isinstance(response_text, list):
        response_text = "\n".join(str(x) for x in response_text)
    try:
        recipe = _parse_json_response(str(response_text))
        recipe = _validate_recipe(recipe)
        await _write_result(hass, {"ts": int(time.time()), "status": "ok", "recipe": recipe})
    except Exception as err:
        preview = str(response_text)[:200] if response_text else "(leer)"
        await _write_error(hass, f"JSON-Parsing fehlgeschlagen: {err}. Antwort: {preview}")


def _parse_json_response(text: str) -> dict:
    """JSON aus KI-Antwort extrahieren und bei Bedarf reparieren.

    Versucht in dieser Reihenfolge:
    1. Direktes json.loads()
    2. json-repair Library (behebt unescapte Zeichen, fehlende Klammern, etc.)
    3. Eigene Fallback-Reparatur
    """
    text = text.strip()

    # Markdown-Fences entfernen
    if "```" in text:
        for part in text.split("```"):
            part = part.strip().lstrip("json").strip()
            try:
                return json.loads(part)
            except Exception:
                continue

    # Direkt parsen
    try:
        return json.loads(text)
    except Exception:
        pass

    # JSON-Objekt aus umgebendem Text herausschneiden
    start, end = text.find("{"), text.rfind("}")
    chunk = text[start:end + 1] if start != -1 and end > start else text

    # json-repair Library (haelt alle KI-typischen JSON-Fehler aus)
    try:
        from json_repair import repair_json  # type: ignore[import]
        repaired = repair_json(chunk, return_objects=True)
        if isinstance(repaired, dict) and repaired:
            _LOGGER.debug("JSON via json-repair repariert")
            return repaired
    except Exception as repair_err:
        _LOGGER.debug("json-repair fehlgeschlagen: %s", repair_err)

    # Eigene Fallback-Reparatur
    if start != -1 and end > start:
        try:
            return _repair_json(chunk)
        except Exception:
            pass

    raise ValueError("Kein gueltiges JSON gefunden")


def _repair_json(text: str) -> dict:
    """Haeufige KI-JSON-Fehler reparieren (Steuerzeichen, Trailing Commas, Truncation)."""
    import re as _re

    # 1. Trailing commas
    repaired = _re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        return json.loads(repaired)
    except Exception:
        pass

    # 2. Unescapte Steuerzeichen in JSON-Strings escapen
    def _escape_ctrl(s: str) -> str:
        out: list[str] = []
        in_str = False
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == "\\" and i + 1 < len(s):
                out.append(ch)
                out.append(s[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = not in_str
                out.append(ch)
            elif in_str and ord(ch) == 10:
                out.append("\\n")
            elif in_str and ord(ch) == 13:
                out.append("\\r")
            elif in_str and ord(ch) == 9:
                out.append("\\t")
            else:
                out.append(ch)
            i += 1
        return "".join(out)

    repaired2 = _escape_ctrl(repaired)
    try:
        return json.loads(repaired2)
    except Exception:
        pass

    # 3. Abgeschnittenes JSON: letzten unvollstaendigen Eintrag entfernen
    candidate = repaired2
    for _ in range(15):
        last_comma = candidate.rfind(",")
        if last_comma < 0:
            break
        candidate = candidate[:last_comma]
        opens     = candidate.count("{") - candidate.count("}")
        arr_opens = candidate.count("[") - candidate.count("]")
        if opens >= 0 and arr_opens >= 0:
            closed = candidate + "]" * arr_opens + "}" * opens
            closed = _re.sub(r",(\s*[}\]])", r"\1", closed)
            try:
                return json.loads(closed)
            except Exception:
                continue

    raise ValueError("JSON-Reparatur fehlgeschlagen")


def _validate_recipe(r: dict) -> dict:
    r.setdefault("title",        "Importiertes Rezept")
    r.setdefault("subtitle",     "")
    r.setdefault("emoji",        "\U0001f373")
    if not r.get("emoji"):
        r["emoji"] = "\U0001f373"
    r.setdefault("category",     "")
    r.setdefault("description",  "")
    r.setdefault("servingLabel", "Portionen")
    r.setdefault("notes",        [])
    try:
        r["baseServings"] = max(1, int(r.get("baseServings", 4)))
    except (ValueError, TypeError):
        r["baseServings"] = 4
    cleaned_ings = []
    for ing in r.get("ingredients", []):
        if not isinstance(ing, dict):
            continue
        try:
            ing["amount"] = float(ing.get("amount", 0)) or 0.0
        except (ValueError, TypeError):
            ing["amount"] = 0.0
        if ing.get("unit") not in VALID_UNITS:
            ing["unit"] = "g"
        ing.setdefault("name", "")
        if ing["name"]:
            cleaned_ings.append(ing)
    r["ingredients"] = cleaned_ings
    cleaned_steps = []
    for step in r.get("steps", []):
        if not isinstance(step, dict):
            continue
        try:
            step["timerSec"] = max(0, int(step.get("timerSec", 0)))
        except (ValueError, TypeError):
            step["timerSec"] = 0
        try:
            step["airfryerTemp"] = max(0, int(step.get("airfryerTemp", 0)))
        except (ValueError, TypeError):
            step["airfryerTemp"] = 0
        try:
            step["airfryerTime"] = max(0, int(step.get("airfryerTime", 0)))
        except (ValueError, TypeError):
            step["airfryerTime"] = 0
        step.setdefault("text", "")
        if step["text"]:
            cleaned_steps.append(step)
    r["steps"] = cleaned_steps
    r["notes"] = [str(n) for n in r.get("notes", []) if n]
    return r


# ── Dateihilfsfunktionen ──────────────────────────────────────────────────────

def _result_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www", REZEPTE_DOMAIN, RESULT_FILE))

async def _write_result(hass: HomeAssistant, data: dict) -> None:
    """Ergebnis-JSON asynchron in Executor-Thread schreiben."""
    path    = _result_path(hass)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    await hass.async_add_executor_job(_write)

async def _write_error(hass: HomeAssistant, msg: str) -> None:
    _LOGGER.error("Rezepte Import: %s", msg)
    await _write_result(hass, {"ts": int(time.time()), "status": "error", "error": msg})

def _write_image_file(path: str, b64: str) -> None:
    missing = len(b64) % 4
    if missing:
        b64 += "=" * (4 - missing)
    Path(path).write_bytes(base64.b64decode(b64))

def _delete_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


# ── HTML / JSON-LD Extraktion ─────────────────────────────────────────────────


def _extract_pdf_text(pdf_b64: str) -> str:
    """Text aus PDF-Datei extrahieren (pypdf).

    Gibt leeren String zurueck wenn kein Text gefunden (gescanntes PDF).
    """
    import io as _io
    try:
        import pypdf
    except ImportError:
        raise RuntimeError(
            "pypdf nicht installiert – bitte Home Assistant neu starten "
            "damit die Abhaengigkeit installiert wird."
        )
    missing = len(pdf_b64) % 4
    if missing:
        pdf_b64 += "=" * (4 - missing)
    pdf_bytes = base64.b64decode(pdf_b64)
    reader = pypdf.PdfReader(_io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    return "\n".join(pages).strip()


def _pdf_page_to_image(pdf_b64: str) -> tuple[str, str]:
    """Eingebettetes Bild aus erster PDF-Seite extrahieren (pypdf).

    Funktioniert fuer gescannte PDFs die ein eingebettetes Bild enthalten.
    Gibt (base64_string, mime_type) zurueck.
    """
    import io as _io
    import pypdf

    missing = len(pdf_b64) % 4
    if missing:
        pdf_b64 += "=" * (4 - missing)
    pdf_bytes = base64.b64decode(pdf_b64)
    reader = pypdf.PdfReader(_io.BytesIO(pdf_bytes))

    page = reader.pages[0]
    images = list(page.images)
    if not images:
        raise RuntimeError(
            "Keine eingebetteten Bilder in der PDF gefunden. "
            "Das PDF ist moeglicherweise kein einfacher Scan."
        )
    img = images[0]
    name = (img.name or "").lower()
    if "png" in name:
        mime = "image/png"
    elif "jp" in name:
        mime = "image/jpeg"
    else:
        mime = "image/jpeg"
    return base64.b64encode(img.data).decode(), mime

def _extract_jsonld_recipe(html: str) -> str | None:
    """JSON-LD Recipe-Daten aus HTML extrahieren (Standard bei vielen Rezeptseiten)."""
    import re
    scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )
    for script in scripts:
        try:
            data = json.loads(script.strip())
            if isinstance(data, list):
                data = data[0] if data else {}
            # Manchmal in @graph verschachtelt
            if "@graph" in data:
                for item in data["@graph"]:
                    t = item.get("@type", "")
                    if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
                        data = item
                        break
            rtype = data.get("@type", "")
            if rtype == "Recipe" or (isinstance(rtype, list) and "Recipe" in rtype):
                return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            continue
    return None


class _TextExtractor:
    from html.parser import HTMLParser as _HP

    class _Inner(_HP):
        _SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"}

        def __init__(self):
            super().__init__()
            self._depth = 0
            self.parts: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag in self._SKIP:
                self._depth += 1

        def handle_endtag(self, tag):
            if tag in self._SKIP and self._depth > 0:
                self._depth -= 1

        def handle_data(self, data):
            if not self._depth:
                s = data.strip()
                if s:
                    self.parts.append(s)


def _extract_text_from_html(html: str) -> str:
    from html.parser import HTMLParser

    class Extractor(HTMLParser):
        SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"}

        def __init__(self):
            super().__init__()
            self._d = 0
            self.parts: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag in self.SKIP:
                self._d += 1

        def handle_endtag(self, tag):
            if tag in self.SKIP and self._d > 0:
                self._d -= 1

        def handle_data(self, data):
            if not self._d:
                s = data.strip()
                if s:
                    self.parts.append(s)

    ex = Extractor()
    try:
        ex.feed(html)
    except Exception:
        pass
    return "\n".join(ex.parts)
