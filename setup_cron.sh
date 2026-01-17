#!/bin/bash

# Setup script for EVCC PDF Report Generator Cron Job

# Determine the absolute path of the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check for docker-compose or docker compose
if command -v docker-compose &> /dev/null; then
    DOCKER_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    DOCKER_CMD="docker compose"
else
    echo "Error: docker-compose or 'docker compose' is not available. Please install Docker Compose first."
    exit 1
fi

# Define the cron command
# Runs at 02:00 AM on the 1st of every month
# Navigates to the directory, runs the container, and logs output
CRON_SCHEDULE="0 2 1 * *"
COMMAND="cd $PROJECT_DIR && $DOCKER_CMD up >> $PROJECT_DIR/cron.log 2>&1"
FULL_CRON_ENTRY="$CRON_SCHEDULE $COMMAND"

echo "--------------------------------------------------------"
echo "EVCC PDF Report Generator - Auto-Run Setup"
echo "--------------------------------------------------------"
echo "This script will add a cron job to your system to automatically"
echo "generate and email the report on the 1st of every month at 02:00 AM."
echo ""
echo "Project Directory: $PROJECT_DIR"
echo "Command to add:    $COMMAND"
echo ""

# Check if the job already exists (simple string match)
if crontab -l 2>/dev/null | grep -Fq "$PROJECT_DIR"; then
    echo "Warning: It looks like a cron job for this directory already exists."
fi

read -p "Do you want to add this cron job? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Backup current crontab
    crontab -l > mycron_backup 2>/dev/null
    
    # Append new job to crontab
    (crontab -l 2>/dev/null; echo "$FULL_CRON_ENTRY") | crontab -
    
    echo ""
    echo "✅ Cron job added successfully!"
    echo "You can check your crontab with 'crontab -l'"
    echo "Logs will be written to '$PROJECT_DIR/cron.log'"
else
    echo ""
    echo "❌ Operation cancelled."
fi
