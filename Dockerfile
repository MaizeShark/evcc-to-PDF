# 1. Basis-Image: Python auf Debian-Basis
FROM python:3.11-slim-bookworm

# 2. System-Abhängigkeiten für WeasyPrint und deutsche Locale installieren
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    locales \
    && rm -rf /var/lib/apt/lists/*

# 3. Deutsche Locale generieren und als Standard setzen
RUN sed -i -e 's/# de_DE.UTF-8 UTF-8/de_DE.UTF-8 UTF-8/' /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales && \
    update-locale LANG=de_DE.UTF-8
ENV LANG de_DE.UTF-8
ENV LANGUAGE de_DE:de
ENV LC_ALL de_DE.UTF-8

# 4. Arbeitsverzeichnis im Container erstellen und festlegen
WORKDIR /app

# 5. Python-Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Anwendungsdateien in den Container kopieren
COPY vorlage.html .
COPY pdf_erstellen_auto.py .

# 7. Erstelle einen Ordner für die Ausgabe
RUN mkdir /output

# 8. Befehl, der beim Starten des Containers ausgeführt wird
CMD ["python3", "pdf_erstellen_auto.py"]