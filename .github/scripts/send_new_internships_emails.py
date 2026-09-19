#!/usr/bin/env python3
"""
Daglig e-postvarsling om NYE internships for Internshipradar.

Kjøres som et eget steg RETT ETTER update_internships.py, som skriver dagens
godkjente, nye oppføringer til new_items_today.json (tom liste hvis ingen nye
ble funnet i dag). Sender én samlet e-post til ALLE brukere som har slått på
"Varsle meg om nye internships" — uansett fagfelt, siden dette varselet ikke
filtreres på kategori.

Dette er en helt separat e-postpreferanse ("newItemsNotifyEnabled") fra
fristvarslene i send_deadline_emails.py — en bruker kan ha den ene, begge,
eller ingen av dem påslått.

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
from email.mime.text import MIMEText

NEW_ITEMS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "new_items_today.json")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def load_new_items():
    try:
        with open(NEW_ITEMS_PATH, "r", encoding="utf-8") as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def build_email_body(items):
    lines = [
        "Hei!",
        "",
        "Disse nye internshipsene/sommerjobbene/traineeprogrammene ble lagt til på Internshipradar i dag:",
        "",
    ]
    for it in items:
        title = it.get("title") or "Internship"
        company = it.get("company") or ""
        deadline = it.get("deadline") or ""
        piece = "- " + title
        if company:
            piece += " (" + company + ")"
        if deadline:
            piece += " – frist " + deadline
        lines.append(piece)
    lines.append("")
    lines.append("Gå inn på Internshipradar for å se detaljer og søke: https://internshipradar.no")
    lines.append("")
    lines.append("Du får denne e-posten fordi du har slått på \"Varsle meg om nye internships\" på kontoen din.")
    return "\n".join(lines)


def send_email(smtp, from_addr, to_addr, items):
    subject = "Internshipradar: " + str(len(items)) + " nye internship(s) i dag"
    if len(items) == 1:
        subject = "Internshipradar: ny oppføring – " + (items[0].get("title") or "Internship")
    msg = MIMEText(build_email_body(items), "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    smtp.sendmail(from_addr, [to_addr], msg.as_string())


def main():
    new_items = load_new_items()
    if not new_items:
        print("Ingen nye internships i dag — hopper over nye-internships-varsling.")
        return

    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        print("FIREBASE_SERVICE_ACCOUNT_JSON er ikke satt — hopper over nye-internships-varsling i dag.")
        return

    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_app_password:
        print("GMAIL_ADDRESS/GMAIL_APP_PASSWORD er ikke satt — hopper over nye-internships-varsling i dag.")
        return

    try:
        import firebase_admin
        from firebase_admin import auth as fb_auth
        from firebase_admin import credentials, firestore
    except ImportError:
        print("firebase-admin er ikke installert — hopper over nye-internships-varsling i dag.")
        return

    try:
        cred_data = json.loads(service_account_json)
        cred = credentials.Certificate(cred_data)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print("Klarte ikke å koble til Firebase: " + str(e))
        return

    try:
        users_ref = db.collection("users").stream()
    except Exception as e:
        print("Klarte ikke å hente brukere fra Firestore: " + str(e))
        return

    recipients = []
    user_count = 0
    for user_doc in users_ref:
        user_count += 1
        data = user_doc.to_dict() or {}
        if data.get("newItemsNotifyEnabled"):
            recipients.append(user_doc.id)

    if not recipients:
        print("Sjekket " + str(user_count) + " bruker(e), ingen abonnerer på nye-internships-varsel.")
        return

    try:
        smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
        smtp.login(gmail_address, gmail_app_password)
    except Exception as e:
        print("Klarte ikke å koble til Gmail SMTP — hopper over nye-internships-varsling i dag: " + str(e))
        return

    sent_count = 0
    try:
        for uid in recipients:
            try:
                user_record = fb_auth.get_user(uid)
                to_addr = user_record.email
            except Exception as e:
                print("Fant ikke e-post for bruker " + uid + ": " + str(e))
                continue
            if not to_addr:
                continue

            try:
                send_email(smtp, gmail_address, to_addr, new_items)
                sent_count += 1
            except Exception as e:
                print("Feil ved sending av e-post til bruker " + uid + ": " + str(e))
                continue
    finally:
        try:
            smtp.quit()
        except Exception:
            pass

    print("Sjekket " + str(user_count) + " bruker(e), sendte " + str(sent_count) + " varsel om nye internships.")


if __name__ == "__main__":
    main()
