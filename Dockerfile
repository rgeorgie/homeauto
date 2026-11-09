FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system runtime dependencies:
# - ffmpeg: required for camera RTSP/video streaming and live snapshots
# - curl: for healthcheck and container inspection
# - procps: for system process inspections
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    procps \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend, frontend, and templates
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY config.example.yaml ./config.example.yaml

# Expose HomeAuto HTTP port (default 80)
EXPOSE 80

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:80/api/status || exit 1

# Default command to run the backend server
CMD ["python", "-m", "backend.main"]
