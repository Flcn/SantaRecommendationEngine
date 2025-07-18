FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code and set ownership
COPY --chown=appuser:appuser . .

# Make entrypoint script executable
RUN chmod +x entrypoint.sh

# Switch to non-root user
USER appuser

# Health check (works for both server and worker modes)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import asyncio; from app.database import db; asyncio.run(db.init_pools())" || exit 1

# Expose port
EXPOSE 8000

# Use entrypoint script to determine startup mode
ENTRYPOINT ["./entrypoint.sh"]