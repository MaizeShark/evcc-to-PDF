# 1. Base image: Python on Debian base
FROM python:3.11-slim-bookworm

# 2. Install system dependencies for WeasyPrint and locales
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    locales \
    && rm -rf /var/lib/apt/lists/*

# 3. Set default locale to be configurable via build argument
ARG LOCALE=de_DE.UTF-8
RUN sed -i -e "s/# $LOCALE UTF-8/$LOCALE UTF-8/" /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales && \
    update-locale LANG=$LOCALE
ENV LANG $LOCALE
ENV LANGUAGE ${LOCALE%.*}:${LOCALE%_*}
ENV LC_ALL $LOCALE

# 4. Create and set the working directory in the container
WORKDIR /app

# 5. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy application files into the container
COPY template_*.html .
COPY generate_pdf_report.py .

# 8. Command to execute when starting the container
CMD ["python3", "generate_pdf_report.py"]
