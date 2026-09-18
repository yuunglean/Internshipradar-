#!/usr/bin/env python3
"""
Daglig push-varsling for Internshipradar.

Kjøres som et eget steg RETT ETTER at update_internships.py har oppdatert
data.json. Leser alle brukeres Firestore-dokumenter (via Firebase Admin SDK,
som ikke er begrenset av de vanlige sikkerhetsreglene), finner favorittmerkede
internships med søknadsfrist innen 3 dager, og sender et push-varsel (Firebase
Cloud Messaging) til hver av brukerens registrerte enheter.

Skal ALDRI kunne få hele workflowen til å feile: hvis noe går galt her (mangler
secret, Firestore utilgjengelig, osv.) logger vi det og avslutter stille, slik
at den daglige data.json-oppdateringen uansett blir committet.
"""

import json
import os
import sys
from datetime import date, datetime

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data.json")

# Statuser brukeren selv har markert som ikke lenger aktuelle — ikke varsle om disse.
SKIP_STATUSES = {"avslått", "ikke aktuell"}


def today_key():
    return date.today().isoformat()


def days_until(deadline_str):
    try:
        d = date.fromisoformat(deadline_str)
    except (TypeError, ValueError):
        return None
    return (d - date.today()).days


def load_deadline_map():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)
    out = {}
    for it in items:
        item_id = it.get("id")
        deadline = it.get("deadline")
        if item_id and deadline:
            out[item_id] = {
                "deadline": deadline,
                "title": it.get("title") or "Internship",
                "company": it.get("company") or "",
            }
    return out


def deadline_label(days):
    if days == 0:
        return "Frist i dag"
    if days == 1:
        return "1 dag igjen"
    return str(days) + " dager igjen"


def main():
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        print("FIREBASE_SERVICE_ACCOUNT_JSON er ikke satt — hopper over push-varsling i dag.")
        return

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, messaging
    except ImportError:
        print("firebase-admin er ikke installert — hopper over push-varsling i dag.")
        return

    try:
        cred_data = json.loads(service_account_json)
        cred = credentials.Certificate(cred_data)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print("Klarte ikke å koble til Firebase: " + str(e))
        return

    deadlines = load_deadline_map()
    if not deadlines:
        print("Fant ingen gyldige frister i data.json — ingenting å varsle om.")
        return

    tkey = today_key()
    sent_count = 0
    user_count = 0

    try:
        users_ref = db.collection("users").stream()
    except Exception as e:
        print("Klarte ikke å hente brukere fra Firestore: " + str(e))
        return

    for user_doc in users_ref:
        user_count += 1
        data = user_doc.to_dict() or {}
        tokens = data.get("fcmTokens") or []
        if not tokens:
            continue

        overlay = data.get("overlay") or {}
        notified_server = data.get("notifiedServer") or {}
        valid_tokens = list(tokens)
        tokens_to_remove = []
        notified_updates = {}

        for item_id, ov in overlay.items():
            if not isinstance(ov, dict) or not ov.get("favorite"):
                continue
            if ov.get("myStatus") in SKIP_STATUSES:
                continue
            info = deadlines.get(item_id)
            if not info:
                continue
            days = days_until(info["deadline"])
            if days is None or days < 0 or days > 3:
                continue
            if notified_server.get(item_id) == tkey:
                continue

            title = "Frist nærmer seg: " + info["title"]
            body = info["company"] + " – " + deadline_label(days)

            any_sent = False
            for token in list(valid_tokens):
                try:
                    messaging.send(messaging.Message(
                        notification=messaging.Notification(title=title, body=body),
                        data={"tag": "internshipradar-" + item_id, "url": "./"},
                        token=token,
                    ))
                    any_sent = True
                    sent_count += 1
                except messaging.UnregisteredError:
                    tokens_to_remove.append(token)
                except Exception as e:
                    print("Feil ved sending til token for bruker " + user_doc.id + ": " + str(e))

            if any_sent:
                notified_updates[item_id] = tkey

        updates = {}
        if notified_updates:
            merged_notified = dict(notified_server)
            merged_notified.update(notified_updates)
            updates["notifiedServer"] = merged_notified
        if tokens_to_remove:
            remaining = [t for t in valid_tokens if t not in tokens_to_remove]
            updates["fcmTokens"] = remaining

        if updates:
            try:
                user_doc.reference.update(updates)
            except Exception as e:
                print("Klarte ikke å oppdatere bruker " + user_doc.id + ": " + str(e))

    print("Sjekket " + str(user_count) + " bruker(e), sendte " + str(sent_count) + " push-varsel/varsler.")


if __name__ == "__main__":
    main()
