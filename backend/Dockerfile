# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Prevent python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
# Ensure python output is sent straight to terminal (useful for logs)
ENV PYTHONUNBUFFERED 1

# Install system dependencies if any (e.g., if specific libraries needed them)
# RUN apt-get update && apt-get install -y --no-install-recommends some-package && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .
# Install any needed packages specified in requirements.txt
# Using --no-cache-dir to reduce image size
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend application code into the container at /app
COPY . .

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Define environment variables (placeholders, will be overridden by compose/env_file)
ENV MONGO_URL=""
ENV OPENAI_API_KEY=""
ENV JAI_API_KEY=""
ENV JAI_BASE_URL=""
ENV TYPHOON_API_KEY=""
ENV TYPHOON_BASE_URL=""
ENV GEMMA_API_KEY=""
ENV GEMMA_BASE_URL=""
ENV LANGFUSE_SECRET_KEY=""
ENV LANGFUSE_PUBLIC_KEY=""
ENV LANGFUSE_HOST=""
ENV PORT=8000
ENV HOST=0.0.0.0
ENV GEMINI_API_KEY=""
# Run uvicorn server when the container launches
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]