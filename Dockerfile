# Keep the container simple and predictable: it only needs Python itself
# because the application intentionally avoids third-party runtime packages.
FROM python:3.11-slim

WORKDIR /app

# Copy the whole project so the web app, CLI wrapper, and tests are all available.
COPY . .

ENV PORT=8000

EXPOSE 8000

# `app.py` reads PORT and binds to 0.0.0.0, which makes it work both locally
# and on the target containers server.
CMD ["python", "app.py"]
