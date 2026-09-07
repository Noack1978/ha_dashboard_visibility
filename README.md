# 📋 Rezepte Import – Erweiterung für ha-rezepte

Optionale Import-Erweiterung für die [ha-rezepte](https://github.com/Noack1978/ha-rezepte) Integration.
Ermöglicht das Importieren von Rezepten aus Text, Textdateien, Weblinks und Bildern direkt in die Rezepte-App.

---

## Voraussetzungen

### Zwingend erforderlich

**[ha-rezepte](https://github.com/Noack1978/ha-rezepte)** muss installiert und eingerichtet sein.

**Ein Konversationsagent** muss in HA konfiguriert sein – er wird für Text-, Link- und Datei-Import verwendet.
Empfohlen: Google Generative AI oder Groq (siehe Abschnitt KI-Konfiguration).

---

### Für Text / Link / TXT-Datei Import

Ein **Konversationsagent** in HA genügt. Dieser wird unter **Einstellungen → Sprachassistenten → Konversationsagent** konfiguriert.

**Wichtig bei Google Gemini:** Das Modell `gemini-2.5-flash` hat nur **20 kostenlose Anfragen pro Tag**.
Für regelmäßigen Einsatz auf `gemini-1.5-flash` wechseln (1.500/Tag):
Einstellungen → Integrationen → Google Gemini → Konfigurieren → Modell ändern

---

### Für Bild-Import

Für den Bild-Import wird ein **Groq API-Key** benötigt – der direkt in der
Rezepte Import Konfiguration eingetragen wird (kein separater HA-Agent nötig).

**Groq API-Key erstellen:**

1. [console.groq.com](https://console.groq.com) → kostenloser Account
2. API Keys → Create API Key
3. Key kopieren → in Rezepte Import Konfiguration eintragen

**Empfohlenes Vision-Modell:** `meta-llama/llama-4-maverick-17b-128e-instruct`

Fallback (wenn kein Key eingetragen): LLM Vision Integration. **Hinweis:** LLM Vision 1.6.0 und 1.7.0-rc.1 haben einen bekannten Bug
(`'list' object has no attribute 'split'`) der den Bild-Import verhindert.
Der direkte Groq API-Aufruf umgeht diesen Bug vollständig.

---
## Screenshot
<img width="1220" height="2268" alt="1000062039" src="https://github.com/user-attachments/assets/5857ff8a-fd81-4589-828a-77e4bed55ece" />


## Installation

### Via HACS

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Noack1978&repository=ha-rezepte-import&category=integration)

1. HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories
2. URL dieses Repositories, Kategorie: **Integration**
3. **Rezepte Import** installieren
4. Home Assistant **neu starten**

### Manuell

`custom_components/rezepte_import/` nach `/config/custom_components/rezepte_import/` kopieren,
dann HA neu starten.

---

## Einrichtung

1. **Einstellungen → Integrationen → + Hinzufügen → „Rezepte Import"**
2. Folgende Felder ausfüllen:

| Feld                     | Beschreibung                                   | Beispiel                                    |
| ------------------------ | ---------------------------------------------- | ------------------------------------------- |
| Konversationsagent       | entity\_id des Agenten für Text/Link-Import    | `conversation.google_generative_ai`         |
| LLM Vision Anbieter      | Fallback für Bild-Import (wenn kein Groq-Key)  | `Groq`                                      |
| Groq API-Key             | API-Key für direkten Vision-Aufruf (empfohlen) | `gsk_...`                                   |
| Groq Vision Modell       | Modell für Bilderkennung                       | `meta-llama/llama-4-maverick-17b-128e-instruct` |
| Text/Link Prompt-Modus   | Standard oder eigener Prompt                   | `Standard`                                  |
| Eigener Text/Link-Prompt | Individuelle Anweisung an die KI               | *(vorausgefüllt)*                           |
| Bild Prompt-Modus        | Standard oder eigener Bild-Prompt              | `Standard`                                  |
| Eigener Bild-Prompt      | Individuelle Anweisung für Bilderkennung       | *(vorausgefüllt)*                           |

3. Bestätigen – fertig. Der **📋-Button** erscheint automatisch in der Rezepte-App.

### Einstellungen nachträglich ändern

**Einstellungen → Integrationen → Rezepte Import → ⋮ → Neu konfigurieren**

HA lädt die Integration automatisch neu – kein Neustart nötig.

---

## Import-Methoden

### ✏️ Text

Rezepttext direkt einfügen – beliebiges Format:

- Fließtext aus einem Kochbuch
- Strukturierte Zutatenlisten
- Aus einer Webseite kopierter Text

**Tipp:** Das zuverlässigste Verfahren. Funktioniert mit allen Konversationsagenten.

---

### 📁 Datei

| Dateityp                                     | Verarbeitung                                           | Hinweis                         |
| -------------------------------------------- | ------------------------------------------------------ | ------------------------------- |
| `.txt`                                       | Text wird direkt analysiert                            | Empfohlen                       |
| `.jpg` `.jpeg` `.png` `.webp` `.heic` `.bmp` | Bilderkennung via Groq Vision API                      | Groq API-Key erforderlich       |
| `.pdf`                                       | pypdf Textextraktion oder Bildextraktion → Groq Vision | Groq API-Key für gescannte PDFs |

---

### 📄 PDF

PDF-Dateien werden in zwei Schritten verarbeitet:

**Schritt 1 – Textextraktion (pypdf):** Digitale PDFs (Rezepthefte, als PDF gespeicherte Webseiten) enthalten
maschinenlesbaren Text der direkt extrahiert und über den Konversationsagenten
analysiert wird. Keine extra Konfiguration nötig.

**Schritt 2 – Groq Vision Fallback (für gescannte PDFs):** Wenn kein Text gefunden wird (Foto-Scan, Kameraufnahme als PDF), wird die
erste Seite automatisch als Bild gerendert und über die Groq Vision API
analysiert – genau wie der direkte Bild-Import.

**Voraussetzung für gescannte PDFs:** Groq API-Key in der Konfiguration eingetragen.

| PDF-Typ               | Verarbeitung                           | Voraussetzung |
| --------------------- | -------------------------------------- | ------------- |
| Digitales PDF (Text)  | pypdf → Konversationsagent             | Keine         |
| Gescanntes PDF (Bild) | pypdf Bildextraktion → Groq Vision API | Groq API-Key  |

- Maximale Dateigröße: 10 MB
- `pypdf` wird automatisch von HA installiert

### 🔗 Link

URL einer Rezept-Webseite einfügen. HA ruft die Seite **serverseitig** ab (kein CORS-Problem).

- Webseiten mit **JSON-LD** (chefkoch.de, rezeptwelt.de, allrecipes.com u.v.m.) → sehr zuverlässig
- Andere Webseiten → Seitentext wird extrahiert und analysiert
- **Nicht geeignet:** Login-geschützte und JavaScript-gerenderte Seiten ohne JSON-LD

---

### 🖼️ Bild-Import (Datei-Tab)

**Voraussetzung:** Groq API-Key in der Konfiguration eingetragen.

Der Bild-Import sendet das Bild direkt als base64 an die Groq Vision API –
vollständig ohne LLM Vision. Unterstützte Formate: JPG, PNG, WEBP, HEIC, BMP.

**Ablauf:**

1. Datei-Tab öffnen
2. Bild auswählen (Foto, Screenshot, Scan)
3. „Analysieren" tippen → Groq Vision erkennt Zutaten, Schritte und alle Felder
4. Vorschau prüfen → direkt importieren oder im Formular bearbeiten

**Wenn kein Groq-Key eingetragen ist:** LLM Vision wird als Fallback verwendet – Ergebnis abhängig vom gewählten Anbieter:

| LLM Vision Anbieter | Bild-Import                                   |
| ------------------- | --------------------------------------------- |
| Google              | ❌ Bekannter Bug in v1.6.x / v1.7.0-rc.1       |
| Groq                | ❌ Bekannter Bug in v1.6.x / v1.7.0-rc.1       |
| Anthropic / OpenAI  | ⚠️ Möglicherweise funktionsfähig (ungetestet) |

Bei LLM Vision Bug als Workaround:

1. **Google Lens** auf dem Smartphone
2. Foto aufnehmen → Text erkennen lassen
3. Text kopieren → **Text-Tab** nutzen

---

## KI-Konfiguration

### Google Gemini (Konversationsagent)

Integration: **Google Generative AI** (in HA integriert, kein HACS nötig)

Einrichten: Einstellungen → Integrationen → + → Google Generative AI → API-Key eintragen

| Modell                  | Anfragen/Tag (kostenlos) | Empfehlung         |
| ----------------------- | ------------------------ | ------------------ |
| `gemini-2.5-flash`      | 20/Tag                   | ❌ Zu wenig         |
| `gemini-1.5-flash`      | 1.500/Tag                | ✅ Empfohlen        |
| `gemini-2.5-flash-lite` | höher                    | ✅ Gute Alternative |

**Modell wechseln:** Einstellungen → Integrationen → Google Gemini → Konfigurieren → Modell

---

### Groq (Konversationsagent + Bild-Import)

**Für Text/Link-Import als Konversationsagent:**

1. HACS → Groq Integration installieren → HA neu starten
2. Einstellungen → Integrationen → + → Groq → API-Key eintragen
3. In Rezepte Import: Konversationsagent auf `conversation.groq` setzen

**Für Bild-Import:** Groq API-Key direkt in der Rezepte Import Konfiguration eintragen
(unabhängig davon ob Groq als Konversationsagent eingerichtet ist).

| Modell                    | RPM (kostenlos) | RPD (kostenlos) |
| ------------------------- | --------------- | --------------- |
| `llama-3.3-70b-versatile` | 30              | 1.000/Tag       |
| `llama-3.1-8b-instant`    | 30 (schneller)  | 14.400/Tag      |

**Für Bild-Import** (Vision): `meta-llama/llama-4-maverick-17b-128e-instruct` hat reduzierte Limits: 15 RPM / 500 RPD (kostenlos).

---

### Ollama (lokal, kostenlos, unbegrenzt)

Integration: **Ollama** (in HA integriert seit 2024.4)

**Voraussetzung:** Ollama-Server im lokalen Netzwerk.

Einrichten: Einstellungen → Integrationen → + → Ollama → Server-URL eintragen

Empfohlene Modelle: `llama3.1:8b`, `mistral:7b`

---

### OpenAI

Integration: **OpenAI Conversation** (in HA integriert)

Einrichten: Einstellungen → Integrationen → + → OpenAI Conversation → API-Key eintragen

Kostenpflichtig. Für Rezept-Import empfiehlt sich `gpt-4o-mini`.

---

## Wie es funktioniert

```
Web-App → HA REST API → rezepte_import.*
                              ↓
    Text/Link:   conversation.process  →  Konversationsagent
    Bild:        Groq Vision API direkt (oder LLM Vision als Fallback)
                              ↓
         /config/www/rezepte/import_result.json
                              ↑
         Web-App pollt Ergebnis (max. 45 Sek.)
```

Die eingebaute **Struktur-Validierung** korrigiert automatisch:

- Fehlende Pflichtfelder → werden mit Standardwerten befüllt
- Ungültige Einheiten → werden auf bekannte Einheiten gemappt (g, kg, ml, l, TL, EL, Stk., Prise, n.B.)
- Falsche Datentypen → werden konvertiert

Nach dem Import: Vorschau anzeigen → direkt speichern oder zuerst im Formular bearbeiten.

---

## Fehlerbehebung

| Fehler                                 | Ursache                                     | Lösung                                                             |
| -------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------ |
| „429 Too Many Requests"                | API-Kontingent erschöpft                    | Auf `gemini-1.5-flash` wechseln oder warten                        |
| „High demand / Please try again later" | Gemini Rate Limit (Tageskontingent)         | Auf `gemini-1.5-flash` wechseln                                    |
| „Kein gültiges JSON gefunden"          | KI antwortete kein reines JSON              | Erneut versuchen                                                   |
| „list object has no attribute split"   | LLM Vision Bug 1.6.x / 1.7.0-rc             | Groq API-Key eintragen → Bild-Import läuft direkt über Groq Vision |
| „Action not found"                     | HA-Aktion in dieser Version entfernt        | Groq API-Key für Bilder verwenden                                  |
| Bild-Import: leeres Rezept             | Bild unleserlich oder kein Rezept erkennbar | Google Lens → Text-Tab                                             |
| Link: leeres Rezept                    | JavaScript-gerenderte Seite ohne JSON-LD    | Seitentext manuell kopieren → Text-Tab                             |

---

## Lizenz

MIT


## Changelog

### v1.1.5
- 🐛 Bugfix: `RezepteImportOptionsFlow` folgte nicht dem HA-Standardmuster –
  hatte einen `__init__` mit `self._entry` (verbotenes Muster, verursacht
  in neueren HA-Versionen Fehler) und erbte von `OptionsFlow` statt
  `OptionsFlowWithReload`. `@callback`-Decorator bei `async_get_options_flow`
  ergänzt. Reload passiert jetzt automatisch über `OptionsFlowWithReload`
  statt manuell.

### v1.1.4
- 🍳 Import-Prompt erkennt jetzt Airfryer-Angaben pro Schritt (Temperatur
  °C, Zeit Minuten) und befüllt `airfryerTemp`/`airfryerTime` automatisch –
  passend zu ha-rezepte v1.7.0. Wird nur gesetzt wenn der Schritt oder
  das Rezept explizit Airfryer/Heißluftfritteuse erwähnt.

### v1.1.3
- Groq Vision-Modell aktualisiert: `llama-4-scout-17b-16e-instruct` → `llama-4-maverick-17b-128e-instruct`
  (Scout wird von Groq zum 17. Juli 2026 eingestellt)

### v1.1.2
- Import-Prompt: Keine Mengenangaben mehr in Kochschritten –
  KI verwendet jetzt nur Bezeichnungen wie „das Mehl", „die Butter".
  Die Mengen stehen in der Zutatenliste und werden automatisch skaliert.

