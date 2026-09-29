FROM python:3.11-slim

WORKDIR /app

# Install dependencies in a separate layer for cache efficiency
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Non-root user for security
RUN adduser --disabled-password --gecos '' appuser
USER appuser

EXPOSE 8000

# Use $PORT which Render automatically provides
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]