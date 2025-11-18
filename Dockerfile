FROM python:3.10-slim

WORKDIR /app

# Copy all project files into container
COPY . /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 7860

# Run FastAPI
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "4"]
