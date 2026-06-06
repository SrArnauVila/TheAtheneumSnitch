FROM python:3.9-slim

WORKDIR /app

# Install Chromium and its driver (required for Selenium scraping).
# Using the system package avoids webdriver-manager's x86-only binary downloads,
# which don't work on the Pi's ARM architecture.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "snitch_bot.py"]
