# Use a lightweight Python base image
FROM python:3.10-slim

# Install system dependencies for Chromium and ChromeDriver
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-liberation \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for Selenium
ENV CHROME_BIN=/usr/bin/chromium
ENV DRIVER_BIN=/usr/bin/chromedriver

# Set working directory
WORKDIR /app

# Copy all project files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port your Flask app runs on
EXPOSE 10000

# Start the bot server
CMD ["python", "bot.py"]
