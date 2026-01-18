# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Avoid buffering logs
ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy requirements first (leverages Docker cache)
COPY requirements.txt .

# Install system deps needed for aiohttp and phonenumbers if any
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libssl-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get remove -y --purge build-essential gcc \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy the bot
COPY bot.py .

# Optional: create a non-root user (recommended)
RUN useradd --create-home --shell /bin/bash botuser && chown -R botuser:botuser /app
USER botuser

# Koyeb runs containers; command runs the bot
CMD ["python", "bot.py"]