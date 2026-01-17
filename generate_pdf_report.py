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
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


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

    @classmethod
    def from_env(cls) -> 'Config':
        return cls(
            evcc_url=os.environ.get('EVCC_URL', 'http://localhost:7070'),
            evcc_password=os.environ.get('EVCC_PASSWORD', ''),
            smtp_server=os.environ.get('SMTP_SERVER'),
            smtp_port=int(os.environ.get('SMTP_PORT', 587)),
            sender_email=os.environ.get('SENDER_EMAIL'),
            sender_password=os.environ.get('SENDER_PASSWORD'),
            recipient_email=os.environ.get('RECIPIENT_EMAIL'),
            sender_name=os.environ.get('SENDER_NAME', 'John Doe'),
            sender_street=os.environ.get('SENDER_STREET', 'Sample Street 123'),
            sender_city=os.environ.get('SENDER_CITY', '12345 Sample City'),
            locale=os.environ.get('LOCALE', 'en_US.UTF-8')
        )


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

    def fetch_data(self, year: int, month: int) -> Optional[List[Dict[str, Any]]]:
        api_url = f"{self.config.evcc_url}/api/sessions?lang=en&year={year}&month={month}"
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
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error while fetching data: {e}")
        except requests.exceptions.RequestException:
            logger.error(f"Connection error: Could not reach EVCC at '{self.config.evcc_url}'.")
        return None

    def process_data(self, json_data: List[Dict[str, Any]]) -> pd.DataFrame:
        if not json_data:
            return pd.DataFrame()

        df = pd.DataFrame(json_data)
        mapping = {
            'created': 'Start Time',
            'finished': 'End Time',
            'loadpoint': 'Charging Point',
            'vehicle': 'Vehicle',
            'chargedEnergy': 'Energy (kWh)',
            'price': 'Price'
        }

        # Check for missing columns and handle gracefully
        available_cols = [col for col in mapping.keys() if col in df.columns]
        if not available_cols:
            logger.warning("No expected columns found in data.")
            return pd.DataFrame()

        df = df.rename(columns=mapping)

        # Convert date columns
        for col in ['Start Time', 'End Time']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])

        # Calculate duration
        if 'Start Time' in df.columns and 'End Time' in df.columns:
            df['Charging Duration'] = df['End Time'] - df['Start Time']
            df['Charging Duration'] = df['Charging Duration'].apply(
                lambda td: f"{td.components.hours}h {td.components.minutes}m" if pd.notnull(td) else "N/A"
            )

        relevant_columns = list(mapping.values()) + ['Charging Duration']
        existing_columns = [col for col in relevant_columns if col in df.columns]
        return df[existing_columns]

    def _format_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        df_formatted = df.copy()
        if 'Start Time' in df_formatted.columns:
            df_formatted['Start Time'] = df_formatted['Start Time'].dt.strftime('%Y-%m-%d %H:%M')
        if 'End Time' in df_formatted.columns:
            df_formatted['End Time'] = df_formatted['End Time'].dt.strftime('%Y-%m-%d %H:%M')

        if 'Energy (kWh)' in df_formatted.columns:
            df_formatted['Energy (kWh)'] = df_formatted['Energy (kWh)'].apply(
                lambda x: locale.format_string('%.3f', x, True) if pd.notnull(x) else ""
            )
        if 'Price' in df_formatted.columns:
            df_formatted['Price'] = df_formatted['Price'].apply(
                lambda x: locale.format_string('%.2f', x, True) if pd.notnull(x) else ""
            )
        return df_formatted

    def generate_pdf(self, df: pd.DataFrame, year: int, month: int) -> Tuple[Optional[str], Optional[str]]:
        if df.empty:
            logger.info("No charging sessions found for the specified period. No PDF will be created.")
            return None, None

        if 'Start Time' in df.columns:
            df = df.sort_values(by='Start Time', ascending=True).reset_index(drop=True)

        env = Environment(loader=FileSystemLoader('.'))
        try:
            template = env.get_template(self.template_file)
        except Exception as e:
            logger.error(f"Failed to load template '{self.template_file}': {e}")
            return None, None

        df_formatted = self._format_dataframe(df)

        total_energy = df['Energy (kWh)'].sum() if 'Energy (kWh)' in df.columns else 0
        total_price = df['Price'].sum() if 'Price' in df.columns else 0

        sender_info = {
            "name": self.config.sender_name,
            "street": self.config.sender_street,
            "city": self.config.sender_city
        }

        try:
            month_name = locale.nl_langinfo(locale.MON_1 + month - 1)
        except AttributeError:
            # Fallback for systems where nl_langinfo might not be available or behave differently
            month_name = datetime(year, month, 1).strftime('%B')

        html_string = template.render(
            sender=sender_info,
            creation_date=datetime.now().strftime('%Y-%m-%d'),
            period=f"{month_name} {year}",
            charges=df_formatted.to_dict('records'),
            total_energy=locale.format_string('%.3f', total_energy, True),
            total_price=locale.format_string('%.2f', total_price, True)
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
        if not json_data:
            logger.error("Could not fetch data. Terminating.")
            return

        df = self.process_data(json_data)
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


def main():
    parser = argparse.ArgumentParser(description='Generate EVCC charging report PDF.')
    parser.add_argument('--year', type=int, help='Year for the report (e.g., 2023)')
    parser.add_argument('--month', type=int, help='Month for the report (1-12)')
    args = parser.parse_args()

    config = Config.from_env()
    generator = ReportGenerator(config)
    generator.run(year=args.year, month=args.month)


if __name__ == '__main__':
    main()
