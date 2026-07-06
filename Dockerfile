FROM python:3.9-slim

# Install system dependencies required for compilation and pdf generation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set up non-root user 1000 (default Hugging Face Spaces user)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copy requirements and install dependencies locally to user home
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy all project files and set ownership to user 1000
COPY --chown=user . .

# Set dynamic port environment variable for Hugging Face Spaces (default: 7860)
ENV PORT=7860
EXPOSE 7860

# Run with production-ready gunicorn server
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--timeout", "120", "app:app"]
