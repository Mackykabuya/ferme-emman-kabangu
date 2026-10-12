# Image de l'API + interface web. UN SEUL worker : la simulation des capteurs tourne dans le processus.
FROM python:3.12-slim-trixie

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FERME_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 ferme

WORKDIR /app
COPY apps/api/requirements.txt apps/api/requirements-prod.txt apps/api/requirements-ml.txt apps/api/
RUN pip install -r apps/api/requirements-ml.txt -r apps/api/requirements-prod.txt

COPY apps/api apps/api
COPY ml ml
# Entraîne les deux modèles à la construction (ignoré si déjà présents dans ml/registry)
RUN cd ml && ( [ -f registry/diagnostic_latest.joblib ] || python train_diagnostic.py ) \
    && ( [ -f registry/irrigation_latest.joblib ] || python train_irrigation.py )

RUN mkdir -p /data/sauvegardes && chown -R ferme:ferme /app /data
USER ferme
WORKDIR /app/apps/api
ENV SAUVEGARDES_DOSSIER=/data/sauvegardes
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--workers", "1"]
