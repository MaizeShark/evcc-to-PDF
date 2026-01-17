# EVCC Charging Report Generator

This project automates the generation of PDF charging reports from your [EVCC](https://evcc.io/) instance. It fetches charging session data for the previous month, formats it into a PDF report, and optionally sends it via email.

**This project is designed primarily as a Dockerized solution.**

## Features

- 📊 **Automated Reporting:** Fetches charging sessions from the EVCC API for the previous month.
- 📄 **PDF Generation:** Creates formatted PDF reports including session details, total energy, and total cost.
- 📧 **Email Delivery:** Automatically emails the generated PDF to a specified recipient.
- 🐳 **Docker Support:** Simple deployment using Docker Compose.
- 🌍 **Localization:** Supports locale settings for date and number formatting.

## Quick Start (Docker)

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd evcc-to-PDF
    ```

2.  **Configure the environment:**
    Copy the example configuration file and edit it with your details.
    ```bash
    cp .env.example .env
    nano .env
    ```

    **Configuration Variables:**
    
    | Variable | Description | Default |
    |----------|-------------|---------|
    | `EVCC_URL` | URL of your EVCC instance | `http://192.168.178.16:7070` |
    | `EVCC_PASSWORD` | Password for EVCC (if authentication is enabled) | *(empty)* |
    | `SMTP_SERVER` | SMTP Server address | *(Required for email)* |
    | `SMTP_PORT` | SMTP Server port | `587` |
    | `SENDER_EMAIL` | Email address sending the report | *(Required for email)* |
    | `SENDER_PASSWORD` | Password for the sender email | *(Required for email)* |
    | `RECIPIENT_EMAIL` | Recipient email address | *(Required for email)* |
    | `SENDER_NAME` | Name displayed in the PDF header | `John Doe` |
    | `SENDER_STREET` | Street address in PDF header | `Sample Street 123` |
    | `SENDER_CITY` | City/Zip in PDF header | `12345 Sample City` |
    | `LOCALE` | Locale for date/number formatting | `de_DE.UTF-8` |

3.  **Run with Docker Compose:**
    ```bash
    docker-compose up --build
    ```

    The generated PDF will be available in the `./pdfs` directory.

## Local Development (Optional)

If you wish to run the script without Docker (e.g., for development):

1.  **Install dependencies:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
    *Note: `WeasyPrint` requires system dependencies (like `libpango-1.0-0`) which are automatically handled in the Docker image.*

2.  **Run the script:**
    Ensure your environment variables are set (or use a `.env` loader) and run:
    ```bash
    python3 generate_pdf_report.py
    ```
    
    You can also manually specify a year and month:
    ```bash
    python3 generate_pdf_report.py --year 2023 --month 12
    ```

## Customization

- **Templates:** The script uses `vorlage_de.html` by default. You can edit this file to change the PDF layout.