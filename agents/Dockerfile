FROM python:3.11-slim

# Install Tesseract OCR (for Doc Intelligence Agent)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy shared requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all agent code
COPY . .

# Default: overridden per-agent in docker-compose.yml
# e.g., command: python agents/doc-agent/main.py
CMD ["python", "--version"]
