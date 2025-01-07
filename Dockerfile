FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/
COPY scripts/ scripts/
COPY replication_package/ replication_package/
COPY config/ config/

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Default entrypoint for replication
ENTRYPOINT ["python", "replication_package/run_all.py"]
