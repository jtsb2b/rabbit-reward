# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Prevent python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
# Ensure python output is sent straight to terminal
ENV PYTHONUNBUFFERED 1

# Install system dependencies for font handling (needed by matplotlib for custom fonts)
RUN apt-get update && \
    apt-get install -y --no-install-recommends fontconfig && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .
# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir --upgrade pip

RUN pip install --no-cache-dir -r requirements.txt

# Copy the font files into the container
# Make sure the path here matches the location relative to this Dockerfile

# Copy the rest of the frontend application code into the container at /app
COPY . .

# Make port 8501 available
EXPOSE 8501

# Define environment variable for the backend URL (will be overridden by compose)
ENV BACKEND_API_URL=""
ENV STREAMLIT_SERVER_PORT=8501

# Run streamlit when the container launches
CMD ["streamlit", "run", "app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]