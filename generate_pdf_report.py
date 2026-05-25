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
import logging
import argparse
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import sys

# --- LOGGING SETUP ---
# Update logging configuration to send INFO logs to stdout and others to stderr
class InfoFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == logging.INFO

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.INFO)
stdout_handler.addFilter(InfoFilter())

stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[stdout_handler, stderr_handler]
)

logger = logging.getLogger(__name__)

logging.getLogger('fontTools.subset').setLevel(logging.WARN)


# --- COLUMN REGISTRY ---
@dataclass(frozen=True)
class ColumnSpec:
    id: str
    source: Optional[str]      # raw API JSON key, or None for computed
    labels: Dict[str, str]     # locale -> label
    formatter: str             # datetime | string | energy | price | meter | int | duration
    align: str = 'left'        # left | right
    width: int = 10            # approx character width when rendered (header or cell, whichever wider)


# Source field names for odometer / meter readings / loadpoint index are based on
# the user-provided schema; if the live /api/sessions response uses different
# keys, the defensive lookup leaves cells empty rather than crashing.
COLUMNS: List[ColumnSpec] = [
    ColumnSpec('start_time',    'created',       {'en': 'Start Time',        'de': 'Startzeit'},              'datetime', 'left',  16),
    ColumnSpec('end_time',      'finished',      {'en': 'End Time',          'de': 'Endzeit'},                'datetime', 'left',  16),
    ColumnSpec('loadpoint',     'loadpoint',     {'en': 'Charging Point',    'de': 'Ladepunkt'},              'string',   'left',  14),
    ColumnSpec('loadpoint_idx', 'id',            {'en': 'Loadpoint #',       'de': 'Ladepunkt-Nr.'},          'int',      'right', 5),
    ColumnSpec('vehicle',       'vehicle',       {'en': 'Vehicle',           'de': 'Fahrzeug'},               'string',   'left',  14),
    ColumnSpec('odometer',      'odometer',      {'en': 'Odometer (km)',     'de': 'Kilometerstand (km)'},    'int',      'right', 13),
    ColumnSpec('meter_start',   'meterStart',    {'en': 'Meter Start (kWh)', 'de': 'Zählerstand Start (kWh)'},'meter',    'right', 17),
    ColumnSpec('meter_end',     'meterStop',     {'en': 'Meter End (kWh)',   'de': 'Zählerstand Ende (kWh)'}, 'meter',    'right', 17),
    ColumnSpec('energy',        'chargedEnergy', {'en': 'Energy (kWh)',      'de': 'Energie (kWh)'},          'energy',   'right', 12),
    ColumnSpec('duration',      None,            {'en': 'Charging Duration', 'de': 'Ladedauer'},              'duration', 'left',  10),
    ColumnSpec('price',         'price',         {'en': 'Price (€)',         'de': 'Preis (€)'},              'price',    'right', 9),
]

# Rough character-width budgets for the table area on A4 at 10pt sans-serif
# with the current 20mm margins and table padding. Tuned empirically:
#   default 7 columns ≈ 80 weight → portrait fits comfortably
#   ~110 weight → portrait clips, landscape needed
#   ~170 weight → even landscape clips
PORTRAIT_WIDTH_BUDGET = 95
LANDSCAPE_WIDTH_BUDGET = 165

COLUMNS_BY_ID: Dict[str, ColumnSpec] = {c.id: c for c in COLUMNS}

DEFAULT_COLUMNS: List[str] = [
    'start_time', 'end_time', 'loadpoint', 'vehicle', 'energy', 'duration', 'price'
]


def _split_csv(s: str) -> List[str]:
    return [x.strip() for x in s.split(',') if x.strip()]


# --- CONFIGURATION ---
@dataclass
class Config:
    evcc_url: str
    evcc_password: str
    smtp_server: Optional[str]
    smtp_port: int
    sender_email: Optional[str]
    sender_password: Optional[str]
    recipient_email: Optional[str]
    sender_name: str
    sender_street: str
    sender_city: str
    locale: str
    output_folder: str = './output'
    columns: List[str] = field(default_factory=lambda: list(DEFAULT_COLUMNS))
    filter_vehicles: List[str] = field(default_factory=list)
    filter_loadpoints: List[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> 'Config':
        columns_env = _split_csv(os.environ.get('PDF_COLUMNS', ''))
        return cls(
            evcc_url=os.environ.get('EVCC_URL', 'https://demo.evcc.io'),
            evcc_password=os.environ.get('EVCC_PASSWORD', ''),
            smtp_server=os.environ.get('SMTP_SERVER'),
            smtp_port=int(os.environ.get('SMTP_PORT', 587)),
            sender_email=os.environ.get('SENDER_EMAIL'),
            sender_password=os.environ.get('SENDER_PASSWORD'),
            recipient_email=os.environ.get('RECIPIENT_EMAIL'),
            sender_name=os.environ.get('SENDER_NAME', 'John Doe'),
            sender_street=os.environ.get('SENDER_STREET', 'Sample Street 123'),
            sender_city=os.environ.get('SENDER_CITY', '12345 Sample City'),
            locale=os.environ.get('LOCALE', 'en_US.UTF-8'),
            columns=columns_env or list(DEFAULT_COLUMNS),
            filter_vehicles=_split_csv(os.environ.get('FILTER_VEHICLES', '')),
            filter_loadpoints=_split_csv(os.environ.get('FILTER_LOADPOINTS', '')),
        )


def _estimate_table_width(column_ids: List[str]) -> int:
    return sum(COLUMNS_BY_ID[cid].width for cid in column_ids if cid in COLUMNS_BY_ID)


def _choose_orientation(column_ids: List[str]) -> str:
    """Pick page orientation and warn if the table likely clips even in landscape."""
    width = _estimate_table_width(column_ids)
    if width <= PORTRAIT_WIDTH_BUDGET:
        return 'portrait'
    if width <= LANDSCAPE_WIDTH_BUDGET:
        logger.info(
            f"Selected columns have estimated width {width} (portrait budget {PORTRAIT_WIDTH_BUDGET}). "
            f"Using A4 landscape."
        )
    else:
        logger.warning(
            f"Selected columns have estimated width {width} which exceeds the A4 landscape "
            f"budget ({LANDSCAPE_WIDTH_BUDGET}). The table may clip on the right — "
            f"consider removing columns from PDF_COLUMNS. Generating the PDF anyway."
        )
    return 'landscape'


def _validate_columns(columns: List[str]) -> None:
    unknown = [c for c in columns if c not in COLUMNS_BY_ID]
    if unknown:
        logger.error(
            f"Unknown column IDs: {unknown}. Available: {sorted(COLUMNS_BY_ID)}"
        )
        sys.exit(2)


class ReportGenerator:
    def __init__(self, config: Config):
        self.config = config
        self._setup_locale()

    def _setup_locale(self):
        try:
            locale.setlocale(locale.LC_ALL, self.config.locale)
        except locale.Error:
            logger.warning(f"Locale '{self.config.locale}' not found. Defaulting to 'en_US.UTF-8'.")
            locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')

    @property
    def template_file(self) -> str:
        if self.config.locale.startswith('de'):
            return 'template_de.html'
        return 'template_en.html'

    @property
    def _lang(self) -> str:
        return 'de' if self.config.locale.startswith('de') else 'en'

    def fetch_data(self, year: int, month: int) -> Optional[List[Dict[str, Any]]]:
        api_url = f"{self.config.evcc_url}/api/sessions?format=json&lang=en&year={year}&month={month}"
        session = requests.Session()

        if self.config.evcc_password:
            try:
                login_url = f"{self.config.evcc_url}/api/auth/login"
                login_resp = session.post(login_url, json={'password': self.config.evcc_password}, verify=False)
                if login_resp.status_code != 200:
                    logger.error(f"Error during login! Status code: {login_resp.status_code}")
                    return None
            except requests.exceptions.RequestException as e:
                logger.error(f"Connection error during login: {e}")
                return None

        logger.info(f"Fetching charging data for {month}/{year} from {api_url}...")
        try:
            response = session.get(api_url, verify=False)
            response.raise_for_status()
            logger.info("Data fetched successfully.")
            payload = response.json()
            if isinstance(payload, dict) and 'result' in payload:
                return payload['result']
            if isinstance(payload, list):
                return payload  # older evcc shape
            logger.error(f"Unexpected /api/sessions response shape: {type(payload).__name__}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error while fetching data: {e}")
        except requests.exceptions.RequestException:
            logger.error(f"Connection error: Could not reach EVCC at '{self.config.evcc_url}'.")
        return None

    def process_data(self, json_data: List[Dict[str, Any]]) -> pd.DataFrame:
        if not json_data:
            return pd.DataFrame()

        raw = pd.DataFrame(json_data)
        df = pd.DataFrame(index=raw.index)

        for spec in COLUMNS:
            if spec.id == 'duration':
                continue  # computed below
            if spec.source and spec.source in raw.columns:
                df[spec.id] = raw[spec.source]
            else:
                df[spec.id] = pd.NA

        if 'start_time' in df.columns:
            df['start_time'] = pd.to_datetime(df['start_time'], errors='coerce')
        if 'end_time' in df.columns:
            df['end_time'] = pd.to_datetime(df['end_time'], errors='coerce')

        # Duration computed from start/end timestamps.
        if 'start_time' in df.columns and 'end_time' in df.columns:
            td = df['end_time'] - df['start_time']
            df['duration'] = td.apply(
                lambda x: f"{x.components.hours}h {x.components.minutes}m" if pd.notnull(x) else "N/A"
            )
        else:
            df['duration'] = "N/A"

        return df

    def _apply_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        before = len(df)
        if self.config.filter_vehicles and 'vehicle' in df.columns:
            df = df[df['vehicle'].isin(self.config.filter_vehicles)]
        if self.config.filter_loadpoints and 'loadpoint' in df.columns:
            df = df[df['loadpoint'].isin(self.config.filter_loadpoints)]
        after = len(df)
        if before != after:
            logger.info(f"Filters applied: {before} -> {after} rows")
        if before > 0 and after == 0:
            logger.warning("Filter produced empty result — PDF will be empty")
        return df.reset_index(drop=True)

    def _format_dataframe(self, df: pd.DataFrame, selected: List[ColumnSpec]) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        if df.empty:
            for spec in selected:
                out[spec.id] = pd.Series(dtype=str)
            return out

        for spec in selected:
            if spec.id not in df.columns:
                out[spec.id] = ""
                continue
            col = df[spec.id]
            f = spec.formatter
            if f == 'datetime':
                out[spec.id] = col.apply(
                    lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notnull(x) else ""
                )
            elif f == 'energy':
                out[spec.id] = col.apply(
                    lambda x: locale.format_string('%.3f', x, True) if pd.notnull(x) else ""
                )
            elif f == 'price':
                out[spec.id] = col.apply(
                    lambda x: locale.format_string('%.2f', x, True) if pd.notnull(x) else ""
                )
            elif f == 'meter':
                out[spec.id] = col.apply(
                    lambda x: locale.format_string('%.1f', x, True) if pd.notnull(x) else ""
                )
            elif f == 'int':
                out[spec.id] = col.apply(
                    lambda x: str(int(x)) if pd.notnull(x) else ""
                )
            elif f == 'duration':
                out[spec.id] = col.fillna("")
            else:  # 'string' or anything else: passthrough
                out[spec.id] = col.fillna("")
        return out

    def _resolve_selected_columns(self) -> List[ColumnSpec]:
        return [COLUMNS_BY_ID[cid] for cid in self.config.columns]

    def generate_pdf(self, df: pd.DataFrame, year: int, month: int) -> Tuple[Optional[str], Optional[str]]:
        selected = self._resolve_selected_columns()

        if 'start_time' in df.columns and not df.empty:
            df = df.sort_values(by='start_time', ascending=True).reset_index(drop=True)

        env = Environment(loader=FileSystemLoader('.'))
        try:
            template = env.get_template(self.template_file)
        except Exception as e:
            logger.error(f"Failed to load template '{self.template_file}': {e}")
            return None, None

        df_formatted = self._format_dataframe(df, selected)

        total_energy = float(df['energy'].sum()) if ('energy' in df.columns and not df.empty) else 0.0
        total_price = float(df['price'].sum()) if ('price' in df.columns and not df.empty) else 0.0

        lang = self._lang
        columns_for_template = [
            {"id": c.id, "label": c.labels[lang], "align": c.align} for c in selected
        ]
        page_orientation = _choose_orientation([c.id for c in selected])

        sender_info = {
            "name": self.config.sender_name,
            "street": self.config.sender_street,
            "city": self.config.sender_city
        }

        try:
            month_name = locale.nl_langinfo(locale.MON_1 + month - 1)
        except AttributeError:
            month_name = datetime(year, month, 1).strftime('%B')

        charges = df_formatted.to_dict('records') if not df_formatted.empty else []

        html_string = template.render(
            sender=sender_info,
            creation_date=datetime.now().strftime('%Y-%m-%d'),
            period=f"{month_name} {year}",
            columns=columns_for_template,
            charges=charges,
            total_energy=locale.format_string('%.3f', total_energy, True),
            total_price=locale.format_string('%.2f', total_price, True),
            page_orientation=page_orientation,
        )

        pdf_filename = f"ChargingCostSummary_{year}-{month:02d}.pdf"
        os.makedirs(self.config.output_folder, exist_ok=True)
        pdf_path = os.path.join(self.config.output_folder, pdf_filename)

        try:
            HTML(string=html_string).write_pdf(pdf_path)
            logger.info(f"PDF file successfully created: '{pdf_path}'")
            return pdf_path, pdf_filename
        except Exception as e:
            logger.error(f"Failed to write PDF: {e}")
            return None, None

    def send_email(self, subject: str, body: str, attachment_path: str):
        if not all([
            self.config.sender_email,
            self.config.sender_password,
            self.config.recipient_email,
            self.config.smtp_server
        ]):
            logger.warning("Email credentials or server details are incomplete. Email will not be sent.")
            return

        logger.info(f"Preparing email for {self.config.recipient_email}...")
        msg = MIMEMultipart()
        msg['From'] = self.config.sender_email
        msg['To'] = self.config.recipient_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        try:
            with open(attachment_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(attachment_path)}")
            msg.attach(part)
        except IOError as e:
            logger.error(f"Could not read attachment '{attachment_path}': {e}")
            return

        try:
            server = smtplib.SMTP(self.config.smtp_server, self.config.smtp_port)
            server.starttls()
            server.login(self.config.sender_email, self.config.sender_password)
            server.send_message(msg)
            server.quit()
            logger.info("Email sent successfully.")
        except Exception as e:
            logger.error(f"Error while sending the email: {e}")

    def run(self, year: Optional[int] = None, month: Optional[int] = None):
        if year is None or month is None:
            today = datetime.now()
            first_of_this_month = today.replace(day=1)
            last_day_previous_month = first_of_this_month - timedelta(days=1)
            year = year or last_day_previous_month.year
            month = month or last_day_previous_month.month

        logger.info(f"--- Starting report for {month}/{year} ---")

        json_data = self.fetch_data(year, month)
        if json_data is None:
            logger.error("Could not fetch data. Terminating.")
            return

        df = self.process_data(json_data)
        df = self._apply_filters(df)
        pdf_path, pdf_filename = self.generate_pdf(df, year, month)

        if pdf_path:
            try:
                month_name = locale.nl_langinfo(locale.MON_1 + month - 1)
            except AttributeError:
                month_name = datetime(year, month, 1).strftime('%B')

            subject = f"Charging Cost Summary for {month_name} {year}"
            body = f"Attached is the automatic charging cost summary for {month_name} {year}."
            self.send_email(subject, body, pdf_path)

        logger.info("--- Script finished ---")


def _flatten_csv_args(values: List[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        out.extend(_split_csv(v))
    # de-dupe while keeping order
    seen = set()
    deduped = []
    for v in out:
        if v not in seen:
            seen.add(v)
            deduped.append(v)
    return deduped


def main():
    parser = argparse.ArgumentParser(description='Generate EVCC charging report PDF.')
    parser.add_argument('--year', type=int, help='Year for the report (e.g., 2026)')
    parser.add_argument('--month', type=int, help='Month for the report (1-12)')
    parser.add_argument('--columns', type=str,
                        help=f"Comma-separated column IDs. Available: {','.join(c.id for c in COLUMNS)}")
    parser.add_argument('--vehicle', action='append', default=[],
                        help='Filter to this vehicle name. Repeatable, also accepts comma-separated values.')
    parser.add_argument('--loadpoint', action='append', default=[],
                        help='Filter to this loadpoint name. Repeatable, also accepts comma-separated values.')
    args = parser.parse_args()

    config = Config.from_env()

    if args.columns:
        config.columns = _split_csv(args.columns)
    if args.vehicle:
        config.filter_vehicles = _flatten_csv_args(args.vehicle)
    if args.loadpoint:
        config.filter_loadpoints = _flatten_csv_args(args.loadpoint)

    _validate_columns(config.columns)

    generator = ReportGenerator(config)
    generator.run(year=args.year, month=args.month)


if __name__ == '__main__':
    main()
