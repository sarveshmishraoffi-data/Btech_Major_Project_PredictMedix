FROM python:3.9-slim

# Install system dependencies required for compilation and pdf generation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Set dynamic port environment variable for Hugging Face Spaces (default: 7860)
ENV PORT=7860
EXPOSE 7860

# Run with production-ready gunicorn server
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--timeout", "120", "app:app"]
