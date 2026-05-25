# EVCC Charging Report Generator

This project automates the generation of PDF charging reports from your [EVCC](https://evcc.io/) instance. It fetches charging session data for the previous month, formats it into a PDF report, and optionally sends it via email.

**This project is designed primarily as a Dockerized solution.**

## Features

- 📊 **Automated Reporting:** Fetches charging sessions from the EVCC API for the previous month.
- 📄 **PDF Generation:** Creates formatted PDF reports including session details, total energy, and total cost.
- 🧩 **Configurable Columns:** Pick which fields appear in the table (start/end time, vehicle, loadpoint, odometer, meter readings, energy, duration, price).
- 🔍 **Filtering:** Limit a report to specific vehicles or loadpoints, useful for per-car reports.
- 📧 **Email Delivery:** Automatically emails the generated PDF to a specified recipient.
- 🐳 **Docker Support:** Simple deployment using Docker Compose.
- 🌍 **Localization:** Supports locale settings for date and number formatting.

## Quick Start (Docker)

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/MaizeShark/evcc-to-PDF
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
    | `EVCC_URL` | URL of your EVCC instance | `http://localhost:7070` |
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
    | `PDF_COLUMNS` | Comma-separated column IDs to include in the table (see [Columns](#columns--filtering)) | `start_time,end_time,loadpoint,vehicle,energy,duration,price` |
    | `FILTER_VEHICLES` | Comma-separated vehicle whitelist (empty = all). | *(empty)* |
    | `FILTER_LOADPOINTS` | Comma-separated loadpoint whitelist (empty = all). | *(empty)* |

3.  **Run with Docker Compose:**
    ```bash
    docker-compose up --build
    ```

    The generated PDF will be available in the `./output` directory.

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

## Columns & Filtering

You can control which columns appear in the PDF and limit the report to specific vehicles or loadpoints. Configuration can be supplied either via environment variables or CLI flags. CLI flags override the corresponding env var.

### Available column IDs

| ID | Description |
|----|-------------|
| `start_time` | Session start (RFC3339 → formatted as `YYYY-MM-DD HH:MM`) |
| `end_time` | Session end |
| `loadpoint` | Loadpoint name (e.g. *Garage*) |
| `loadpoint_idx` | Loadpoint index (1-based, from evcc's `id` field) |
| `vehicle` | Vehicle name |
| `odometer` | Odometer reading in km (vehicle-side, see caveat below) |
| `meter_start` | Meter reading at start of session (kWh, from the charger) |
| `meter_end` | Meter reading at end of session (kWh, from the charger) |
| `energy` | Charged energy (kWh) |
| `duration` | Charging duration (computed from start/end) |
| `price` | Price (€) |

> **Odometer caveat:** `odometer` comes from the vehicle's own API and is only populated for vehicles that report it. A vehicle configured in evcc as **"Generic vehicle (without API)"** will leave this column blank. See the [evcc vehicle docs](https://docs.evcc.io/en/vehicles/) if yours is compatible.

### Page orientation

The report is rendered on A4 portrait by default. If the selected columns would be too wide for portrait, the report automatically switches to A4 landscape and logs an INFO message. If even landscape isn't wide enough, a WARNING is logged but the PDF is still generated (so the email still goes out)!

### Examples

Default behaviour (unchanged if you set no new variables):
```bash
python3 generate_pdf_report.py
```

Only Nissan Leaf sessions, with odometer and meter readings:
```bash
PDF_COLUMNS=start_time,vehicle,odometer,meter_start,meter_end,energy \
FILTER_VEHICLES="Nissan Leaf" \
python3 generate_pdf_report.py
```

CLI flags (override env per run, names with spaces should be quoted):
```bash
python3 generate_pdf_report.py \
  --columns start_time,vehicle,energy,duration \
  --vehicle "Nissan Leaf" \
  --vehicle "Tesla Model 3" \
  --loadpoint Garage \
  --year 2026 \
  --month 4
```

`--vehicle` and `--loadpoint` are repeatable and also accept comma-separated lists. Unknown column IDs cause the script to exit with code 2 and print the list of valid IDs.

## Customization

- **Templates:** The script uses `template_de.html` (or `template_en.html`) by default depending on locale. You can edit these files to change the PDF layout. The `<thead>` and `<tbody>` are driven by the configured columns, change `PDF_COLUMNS` rather than editing the template if you only want to reorder/hide columns.

## Automation

You can set up this tool to run automatically on the 1st of every month to generate the report for the previous month.

### Option 1: Automatic Setup (Recommended)

Run the included setup script to automatically add a cron job to your system:

```bash
./setup_cron.sh
```

This will configure a job to run at **02:00 AM on the 1st of every month**.

### Option 2: Manual Cron Setup

1.  Open your crontab:
    ```bash
    crontab -e
    ```

2.  Add the following line (adjust the path to your installation):
    ```cron
    0 2 1 * * cd /path/to/evcc-to-PDF && docker-compose up >> cron.log 2>&1
    ```