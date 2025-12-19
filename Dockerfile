# Use a lightweight Python 3.9 image
FROM python:3.9-slim

# 1. Install system dependencies (needed for bcrypt and mysql drivers)
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Set the working directory
WORKDIR /app

# 3. Copy dependencies list and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the rest of the application code
COPY . .

# 5. Expose the port (Render uses 10000 by default for some apps, or 80)
EXPOSE 80

# 6. Command to start the server using Gunicorn
# "app:app" means "look in app.py for the 'app' object"
CMD ["gunicorn", "-b", "0.0.0.0:80", "app:app"]