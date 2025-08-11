FROM python:3.10-slim

# Install system dependencies, including SQLite
RUN apt-get update && apt-get install -y \
    sqlite3 \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements.txt and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port
EXPOSE 8080

# Start the application
CMD ["python", "webhook/app.py"]

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=UTF-8