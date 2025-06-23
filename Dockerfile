# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port for Web UI (default 8000)
EXPOSE 8000

# Set environment variables for Flask
ENV FLASK_APP=web_ui_plugin/web_ui.py
ENV PYTHONUNBUFFERED=1

# Default command
CMD ["python", "web_ui_plugin/web_ui.py"]
