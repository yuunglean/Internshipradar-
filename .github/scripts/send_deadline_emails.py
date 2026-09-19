#!/usr/bin/env python3
"""
Daglig e-postvarsling for Internshipradar.

Kjøres som et eget steg RETT ETTER at update_internships.py har oppdatert
data.json. Leser alle brukeres Firestore-dokumenter (via Firebase Admin SDK,
som ikke er begrenset av de vanlige sikkerhetsreglene), finner favorittmerkede
internships med søknadsfrist innen 3 dager for brukere som har slått på
"Varsle meg om frister", og sender én samlet e-post per bruker via Gmail SMTP.

E-postadressen hentes IKKE fra Firestore (den lagres aldri der) — den hentes
direkte fra brukerens Firebase Auth-konto via Admin SDK-et, basert på UID-en
som er dokumentnavnet i "users"-samlingen.

Skal ALDRI kunne få hele workflowen til å feile: hvis noe går galt her (mangler
secret, Firestore/SMTP utilgjengelig, osv.) logger vi det og avslutter stille,
slik at den daglige data.json-oppdateringen uansett blir committet.
"""

import json
import os
import smtplib
from datetime import date
from email.mime.text import MIMEText

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data.json")

# Statuser brukeren selv har markert som ikke lenger aktuelle — ikke varsle om disse.
SKIP_STATUSES = {"avslått", "ikke aktuell"}

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


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


def build_email_body(due_items):
    lines = [
        "Hei!",
        "",
        "Disse favorittmerkede internshipsene dine har søknadsfrist snart:",
        "",
    ]
    for it in due_items:
        lines.append("- " + it["title"] + " (" + it["company"] + ") – " + deadline_label(it["days"]))
    lines.append("")
    lines.append("Gå inn på Internshipradar for å se detaljer og søke: https://internshipradar.no")
    lines.append("")
    lines.append("Du får denne e-posten fordi du har slått på \"Varsle meg om frister\" på kontoen din.")
    return "\n".join(lines)


def send_email(smtp, from_addr, to_addr, due_items):
    subject = "Internshipradar: " + str(len(due_items)) + " frist(er) nærmer seg"
    if len(due_items) == 1:
        subject = "Internshipradar: frist nærmer seg – " + due_items[0]["title"]
    msg = MIMEText(build_email_body(due_items), "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    smtp.sendmail(from_addr, [to_addr], msg.as_string())


def main():
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        print("FIREBASE_SERVICE_ACCOUNT_JSON er ikke satt — hopper over e-postvarsling i dag.")
        return

    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_app_password:
        print("GMAIL_ADDRESS/GMAIL_APP_PASSWORD er ikke satt — hopper over e-postvarsling i dag.")
        return

    try:
        import firebase_admin
        from firebase_admin import auth as fb_auth
        from firebase_admin import credentials, firestore
    except ImportError:
        print("firebase-admin er ikke installert — hopper over e-postvarsling i dag.")
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

    try:
        users_ref = db.collection("users").stream()
    except Exception as e:
        print("Klarte ikke å hente brukere fra Firestore: " + str(e))
        return

    # Regn ut hvem som faktisk trenger en e-post FØR vi åpner SMTP-tilkoblingen,
    # slik at vi ikke logger inn på Gmail unødvendig hvis ingen skal varsles i dag.
    pending = []  # [(user_doc, uid, [due_items], notified_server)]
    user_count = 0
    for user_doc in users_ref:
        user_count += 1
        data = user_doc.to_dict() or {}
        if not data.get("emailNotifyEnabled"):
            continue

        overlay = data.get("overlay") or {}
        notified_server = data.get("notifiedServer") or {}
        due_items = []

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
            due_items.append({"id": item_id, "title": info["title"], "company": info["company"], "days": days})

        if due_items:
            pending.append((user_doc, due_items, notified_server))

    if not pending:
        print("Sjekket " + str(user_count) + " bruker(e), ingen med nye fristvarsler i dag.")
        return

    try:
        smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
        smtp.login(gmail_address, gmail_app_password)
    except Exception as e:
        print("Klarte ikke å koble til Gmail SMTP — hopper over e-postvarsling i dag: " + str(e))
        return

    sent_count = 0
    try:
        for user_doc, due_items, notified_server in pending:
            try:
                user_record = fb_auth.get_user(user_doc.id)
                to_addr = user_record.email
            except Exception as e:
                print("Fant ikke e-post for bruker " + user_doc.id + ": " + str(e))
                continue
            if not to_addr:
                continue

            try:
                send_email(smtp, gmail_address, to_addr, due_items)
                sent_count += 1
            except Exception as e:
                print("Feil ved sending av e-post til bruker " + user_doc.id + ": " + str(e))
                continue

            merged_notified = dict(notified_server)
            for it in due_items:
                merged_notified[it["id"]] = tkey
            try:
                user_doc.reference.update({"notifiedServer": merged_notified})
            except Exception as e:
                print("Klarte ikke å oppdatere bruker " + user_doc.id + ": " + str(e))
    finally:
        try:
            smtp.quit()
        except Exception:
            pass

    print("Sjekket " + str(user_count) + " bruker(e), sendte " + str(sent_count) + " e-postvarsel/varsler.")


if __name__ == "__main__":
    main()
