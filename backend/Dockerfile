# One image for the API and the worker; compose.yaml picks the command.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app
WORKDIR /app

# Dependencies first (cached until pyproject.toml changes). The app itself runs from /app, not
# site-packages, so templates.yaml and the Alembic scripts sit next to it.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && pip uninstall -y lab-deploy && rm -rf app build *.egg-info
COPY . .
RUN useradd --system --no-create-home labdeploy
USER labdeploy

EXPOSE 8000
# Migrate, then serve. The worker overrides this with its own command.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.api:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
