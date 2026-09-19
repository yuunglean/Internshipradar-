#!/usr/bin/env python3
"""
Daglig research-jobb for Internshipradar.

Bruker Claude (med server-side nettsøk) til å lete etter nye internships,
sommerjobber og traineeprogram innen business/økonomi i Norge, og legger
kun til NYE, unike oppføringer i data.json. Endrer aldri eksisterende
oppføringer.
"""

import json
import os
import re
import sys
from datetime import date

import anthropic

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data.json")

# Skrives av denne jobben hver dag (tom liste hvis ingen nye) og leses av
# send_new_internships_emails.py rett etter, slik at den kan sende ut et
# e-postvarsel om nøyaktig dagens nye oppføringer uten å måtte diffe data.json
# selv. Aldri en fil som committes — kun et scratch-resultat for denne kjøringen.
NEW_ITEMS_PATH = os.path.join(os.path.dirname(DATA_PATH), "new_items_today.json")

FIELD_OPTIONS = [
    "Consulting",
    "Revisjon & rådgivning",
    "Kapitalforvaltning",
    "Investeringsbank & finans",
    "Industri/business",
    "Annet",
]

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = f"""Du er en research-assistent som holder en liste over ekte internships,
sommerjobber og traineeprogram innen business/økonomi i Norge oppdatert.

Reglene dine:

1. Søk kun etter EKTE utlysninger med en direkte kildelenke (bedriftens karriereside,
   nu.nhhs.no, jobylon, smartrecruiters, reachmee, finn.no e.l.). Finn du ikke en konkret
   kilde, ikke finn på en oppføring.

2. Sjekk disse (og lignende) kilder aktivt: PwC Norge, Deloitte Norge, KPMG Norge, EY Norge,
   Accenture Norge, McKinsey Norge, BCG Norge, Bain Norge, Norsk Hydro, Equinor, DNB,
   SpareBank 1-selskaper (inkl. Odin Forvaltning), Nordea Norge, Norges Bank Investment
   Management (NBIM), Storebrand, Statkraft, Telenor, Aker-selskaper, BDO, Colliers, DNV,
   Longship, Svalner Atlas, Wilhelmsen, If Skadeforsikring, Finansdepartementet, Folketrygdfondet,
   samt nu.nhhs.no (NHH sin jobbportal) for en bredere oversikt. Se også etter andre relevante
   selskaper innen consulting, revisjon, kapitalforvaltning, investeringsbank/finans og
   industri/business som ikke er i denne listen. Kryssjekk alltid at søknadsfristen faktisk
   ligger i fremtiden i dag (ikke ta med utlysninger der fristen allerede har passert).

3. VIKTIG om "title": hent den EKSAKTE stillingstittelen slik den faktisk står i utlysningen
   (f.eks. "Forvaltning Internship 2027", ikke bare "Internship 2027" — ikke fjern ord som
   selskapsnavn/avdeling som er en del av selve tittelen, selv om noe av det samme vises i
   "company"-feltet). Ikke omskriv eller forkort tittelen med mindre den er en hel markedsførings-
   setning (f.eks. "Student og nysgjerrig på revisjon? Vi søker Winter Interns …") — da lager du
   en kort, nøytral tittel som beholder de faktiske nøkkelordene (rolle/team) fra kilden, uten å
   dikte opp noe som ikke står der (f.eks. ikke legg til "M&A" hvis kilden bare sier
   "Strategy & Transactions").

4. VIKTIG om årstall i frister: utlysninger beskriver ofte en internship-periode i ett år
   (f.eks. "sommeren 2027" eller "vinteren 2027"), men SØKNADSFRISTEN ligger nesten alltid
   i inneværende rekrutteringssyklus (typisk høsten {date.today().year} for en internship i
   {date.today().year + 1}), IKKE i selve internship-året. Hvis kilden oppgir en ukedag for
   fristen (f.eks. "søndag 11. oktober"), regn selv ut hvilket år som faktisk stemmer med den
   ukedagen — ikke anta at fristår = internshipår. Sitér helst den eksakte teksten om dato/frist
   fra kilden for deg selv før du konverterer den til YYYY-MM-DD, i stedet for å stole på et
   sammendrag som kan ha lagt til feil årstall. Vær føre-var og dobbeltsjekk dette før du setter
   en dato.

5. Bruk ALDRI ordet "årstrinn". Bruk alltid "kull" når du beskriver hvilke studieår/kull
   internshipet er rettet mot (f.eks. "for 3.-4. kull", ikke "for 3.-4. årstrinn").

6. "field" MÅ være nøyaktig én av disse verdiene: {json.dumps(FIELD_OPTIONS, ensure_ascii=False)}

7. Skriv "description" kort og faktabasert på norsk (maks ca. 200 tegn): periode, varighet,
   fagområde, evt. hvilket kull det er rettet mot. Bruk EKSAKTE datoer når kilden oppgir dem
   (f.eks. "10. juni–13. august 2027" eller "8 uker fra 7. juni 2027"). Bruk ALDRI ordet "medio"
   (verken alene eller i en dobbel konstruksjon som "medio juni–medio august") — det er et ord vi
   ikke skal bruke i det hele tatt. Hvis kilden bare oppgir en omtrentlig dato, skriv det på en mer
   vanlig måte i stedet, f.eks. "midten av juni", "rundt 15. juni" eller bare "i juni".

8. "id" skal være en stabil, url-vennlig slug: kun små bokstaver, tall og bindestrek,
   basert på selskap + tittel + år, f.eks. "pwc-summer-consulting-2028".

9. Ikke inkluder en oppføring hvis den (eller noe svært likt) allerede finnes i listen
   over eksisterende id-er du får oppgitt.

10. Svar KUN med en gyldig JSON-liste av nye oppføringer — ingen forklarende tekst før eller
    etter. Hver oppføring skal ha nøyaktig disse feltene: id, title, company, location, field,
    deadline (YYYY-MM-DD), url, source, description, og valgfritt opensAt (YYYY-MM-DD) hvis
    søknadsvinduet åpner på en kjent, fremtidig dato.

11. Hvis du ikke finner noen nye, ekte oppføringer i dag: svar med en tom liste "[]".
"""


def load_existing():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save(items):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")


def save_new_items_file(items):
    slim = [
        {
            "id": it["id"],
            "title": it["title"],
            "company": it["company"],
            "deadline": it["deadline"],
            "url": it["url"],
        }
        for it in items
    ]
    try:
        with open(NEW_ITEMS_PATH, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception as e:
        print(f"Klarte ikke å skrive new_items_today.json: {e}")


def extract_json_array(text):
    text = text.strip()
    # Strip markdown code fences if present
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Fant ingen JSON-liste i svaret")
    return json.loads(text[start : end + 1])


ID_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
STRING_FIELDS = ["id", "title", "company", "location", "field", "url", "source", "description"]


def validate_item(item, existing_ids, seen_ids):
    required = ["id", "title", "company", "location", "field", "deadline", "url", "source", "description"]
    for key in required:
        if not item.get(key):
            print(f"  Hopper over (mangler '{key}'): {item.get('title', '?')}")
            return False
    # Sikkerhetsnett: hvis modellsvaret av en eller annen grunn ikke er rene
    # tekststrenger (f.eks. en liste/dict pga. en uventet respons), skal vi
    # aldri skrive det rått inn i data.json — klienten forventer strenger.
    for key in STRING_FIELDS:
        if key in item and not isinstance(item[key], str):
            print(f"  Hopper over (feil type på '{key}'): {item.get('title', '?')}")
            return False
    if item["field"] not in FIELD_OPTIONS:
        print(f"  Hopper over (ugyldig field '{item['field']}'): {item['title']}")
        return False
    # "id" skal alltid være en trygg, url-vennlig slug (kun a-z, 0-9 og
    # bindestrek) — dette er allerede det systemprompten ber om (regel 8), men
    # vi håndhever det også her i stedet for å stole blindt på modellsvaret,
    # siden id-en brukes direkte som nøkkel i klientens lokale/synkroniserte data.
    if not ID_SLUG_RE.match(item["id"]):
        print(f"  Hopper over (ugyldig id-format '{item['id']}'): {item['title']}")
        return False
    if item["id"] in existing_ids or item["id"] in seen_ids:
        print(f"  Hopper over (duplikat id): {item['id']}")
        return False
    if not (item["url"].startswith("http://") or item["url"].startswith("https://")):
        print(f"  Hopper over (usikker url-protokoll): {item['title']}")
        return False
    try:
        date.fromisoformat(item["deadline"])
    except ValueError:
        print(f"  Hopper over (ugyldig deadline-format): {item['title']}")
        return False
    if item.get("opensAt"):
        try:
            date.fromisoformat(item["opensAt"])
        except ValueError:
            print(f"  Hopper over (ugyldig opensAt-format): {item['title']}")
            return False
    if "årstrinn" in item.get("description", "").lower():
        item["description"] = re.sub(r"årstrinn", "kull", item["description"], flags=re.IGNORECASE)
    return True


def main():
    existing = load_existing()
    existing_ids = {it["id"] for it in existing}

    client = anthropic.Anthropic()

    user_prompt = (
        "Dagens dato er "
        + date.today().isoformat()
        + ". Eksisterende id-er i listen (ikke dupliser disse):\n"
        + json.dumps(sorted(existing_ids), ensure_ascii=False)
        + "\n\nLet etter nye internships/sommerjobber/traineeprogram innen business/økonomi "
        + "i Norge som ikke allerede er i listen over. Svar med kun en JSON-liste (kan være tom)."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 12}],
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    full_text = "\n".join(text_parts)

    try:
        new_items = extract_json_array(full_text)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Klarte ikke å tolke svaret som JSON: {e}")
        print("--- Rått svar ---")
        print(full_text[:2000])
        sys.exit(0)  # ikke feile hele workflowen for en dårlig dag

    seen_ids = set()
    accepted = []
    for item in new_items:
        if validate_item(item, existing_ids, seen_ids):
            accepted.append(item)
            seen_ids.add(item["id"])

    if not accepted:
        print("Ingen nye, gyldige internships funnet i dag.")
        save_new_items_file([])
        return

    updated = existing + accepted
    save(updated)
    save_new_items_file(accepted)
    print(f"La til {len(accepted)} nye internship(s):")
    for it in accepted:
        print(f"  - {it['company']}: {it['title']} (frist {it['deadline']})")


if __name__ == "__main__":
    main()
