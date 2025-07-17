# Use the official slim Python image (allows apt-get)
FROM python:3.13-slim

# Install Chromium & Chromedriver
RUN apt-get update && \
    apt-get install -y chromium chromium-driver && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your code
COPY . .

# Default command
CMD ["python", "bot.py"]
