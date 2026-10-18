# Keep the container simple and predictable: it only needs Python itself
# because the application intentionally avoids third-party runtime packages.
FROM python:3.11-slim

WORKDIR /app

# Copy the whole project so the web app, CLI wrapper, and tests are all available.
COPY . .

ENV PORT=8000

# Build identification, passed by scripts/deploy.sh (see README). Declared
# after the copy so it never invalidates an earlier layer.
ARG GIT_COMMIT
ARG BUILD_TIME
ENV GIT_COMMIT=$GIT_COMMIT BUILD_TIME=$BUILD_TIME
LABEL org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.created=$BUILD_TIME

EXPOSE 8000

# `app.py` reads PORT and binds to 0.0.0.0, which makes it work both locally
# and on the target containers server.
CMD ["python", "app.py"]
