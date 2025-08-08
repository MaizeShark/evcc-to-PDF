import os
import requests
import pandas as pd
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from datetime import datetime, timedelta
import locale
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# --- KONFIGURATION WIRD AUS UMGEBUNGSVARIABLEN GELESEN ---
EVCC_URL = os.environ.get('EVCC_URL', 'http://192.168.178.16:7070')
EVCC_PASSWORD = os.environ.get('EVCC_PASSWORD', '')

SMTP_SERVER = os.environ.get('SMTP_SERVER')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL')

AUSGABE_ORDNER = '/output'
VORLAGE_DATEI = 'vorlage.html' 
ABSENDER_INFO = {
    "name": os.environ.get('SENDER_NAME', 'Max Mustermann'),
    "strasse": os.environ.get('SENDER_STREET', 'Musterstraße 123'),
    "plz_ort": os.environ.get('SENDER_CITY', '12345 Musterstadt')
}

try:
    locale.setlocale(locale.LC_ALL, 'de_DE.UTF-8')
except locale.Error:
    print("Warnung: Deutsches Sprachpaket 'de_DE.UTF-8' nicht gefunden.")

def sende_email_mit_anhang(subject, body, anhang_pfad):
    if not all([SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL]):
        print("E-Mail-Zugangsdaten unvollständig. E-Mail wird nicht versendet.")
        return
    print(f"Bereite E-Mail für {RECIPIENT_EMAIL} vor...")
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    with open(anhang_pfad, 'rb') as attachment:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(anhang_pfad)}")
    msg.attach(part)
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("E-Mail erfolgreich versendet.")
    except Exception as e:
        print(f"Fehler beim Senden der E-Mail: {e}")

# VOLLSTÄNDIGER CODEBLOCK FÜR daten_von_api_holen
def daten_von_api_holen(url, password, year, month):
    api_url = f"{url}/api/sessions?lang=de&year={year}&month={month}"
    session = requests.Session()
    if password:
        try:
            login_url = f"{url}/api/auth/login"
            login_resp = session.post(login_url, json={'password': password}, verify=False)
            if login_resp.status_code != 200:
                print(f"Fehler bei der Anmeldung! Status-Code: {login_resp.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Verbindungsfehler bei der Anmeldung: {e}")
            return None
    print(f"Rufe Ladedaten für {month}/{year} von {api_url} ab...")
    try:
        response = session.get(api_url, verify=False)
        response.raise_for_status()
        print("Daten erfolgreich abgerufen.")
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP-Fehler beim Abrufen der Daten: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Verbindungsfehler: Konnte EVCC unter '{url}' nicht erreichen.")
    return None

# VOLLSTÄNDIGER CODEBLOCK FÜR json_zu_dataframe
def json_zu_dataframe(json_daten):
    if not json_daten:
        return pd.DataFrame()
    df = pd.DataFrame(json_daten)
    mapping = {
        'created': 'Startzeit',
        'finished': 'Endzeit',
        'loadpoint': 'Ladepunkt',
        'vehicle': 'Fahrzeug',
        'chargedEnergy': 'Energie (kWh)',
        'price': 'Preis'
    }
    df = df.rename(columns=mapping)
    df['Startzeit'] = pd.to_datetime(df['Startzeit'])
    df['Endzeit'] = pd.to_datetime(df['Endzeit'])
    df['Ladedauer'] = df['Endzeit'] - df['Startzeit']
    df['Ladedauer'] = df['Ladedauer'].apply(lambda td: f"{td.components.hours}h {td.components.minutes}m")
    
    # Sicherstellen, dass nur vorhandene Spalten ausgewählt werden
    relevante_spalten = list(mapping.values()) + ['Ladedauer']
    vorhandene_spalten = [col for col in relevante_spalten if col in df.columns]
    return df[vorhandene_spalten]

def erstelle_pdf(df, year, month):
    if df is None or df.empty:
        print("Keine Ladevorgänge im angegebenen Zeitraum gefunden. Es wird keine PDF erstellt.")
        return None
    df = df.sort_values(by='Startzeit', ascending=True).reset_index(drop=True)
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template(VORLAGE_DATEI)
    df_formatiert = df.copy()
    df_formatiert['Startzeit'] = df['Startzeit'].dt.strftime('%d.%m.%Y %H:%M')
    df_formatiert['Endzeit'] = df['Endzeit'].dt.strftime('%d.%m.%Y %H:%M')
    df_formatiert['Energie (kWh)'] = df['Energie (kWh)'].apply(lambda x: locale.format_string('%.3f', x, True))
    df_formatiert['Preis'] = df['Preis'].apply(lambda x: locale.format_string('%.2f', x, True))
    gesamt_energie = df['Energie (kWh)'].sum()
    gesamt_preis = df['Preis'].sum()
    html_string = template.render(
        absender=ABSENDER_INFO,
        erstellungs_datum=datetime.now().strftime('%d.%m.%Y'),
        zeitraum=f"{locale.nl_langinfo(locale.MON_01 + month - 1)} {year}",
        ladungen=df_formatiert.to_dict('records'),
        gesamt_energie=locale.format_string('%.3f', gesamt_energie, True),
        gesamt_preis=locale.format_string('%.2f', gesamt_preis, True)
    )
    pdf_dateiname = f"Ladekostenuebersicht_{year}-{month:02d}.pdf"
    os.makedirs(AUSGABE_ORDNER, exist_ok=True)
    pdf_pfad = os.path.join(AUSGABE_ORDNER, pdf_dateiname)
    HTML(string=html_string).write_pdf(pdf_pfad)
    print(f"PDF-Datei erfolgreich erstellt: '{pdf_pfad}'")
    return pdf_pfad, pdf_dateiname

def main():
    heute = datetime.now()
    erster_dieses_monats = heute.replace(day=1)
    letzter_tag_vormonat = erster_dieses_monats - timedelta(days=1)
    year = letzter_tag_vormonat.year
    month = letzter_tag_vormonat.month
    print(f"--- Starte Report für {month}/{year} ---")
    json_data = daten_von_api_holen(EVCC_URL, EVCC_PASSWORD, year, month)
    if not json_data:
        print("Konnte keine Daten von der API abrufen oder es gab keine Ladevorgänge. Skript wird beendet.")
        return
    df = json_zu_dataframe(json_data)
    result = erstelle_pdf(df, year, month)
    if result:
        pdf_pfad, pdf_dateiname = result
        monats_name = locale.nl_langinfo(locale.MON_01 + month - 1)
        subject = f"Ladekostenübersicht für {monats_name} {year}"
        body = f"Anbei die automatische Ladekostenübersicht für {monats_name} {year}."
        sende_email_mit_anhang(subject, body, pdf_pfad)
    print("--- Skript beendet ---")

if __name__ == '__main__':
    main()