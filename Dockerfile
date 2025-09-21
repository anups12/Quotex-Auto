FROM python:3.9-slim-bullseye

WORKDIR /app

# Install Chrome dependencies
RUN apt-get update && apt-get install -y \
    wget gnupg curl unzip fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libdrm-dev \
    libxkbcommon0 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libnss3 \
    libxss1 libgtk-3-0 xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app

EXPOSE 5000
CMD ["python", "app.py"]
