FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

ENV PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

WORKDIR /workspace/apps/api

COPY requirements.prod.txt ./
RUN pip install --no-cache-dir -r requirements.prod.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

EXPOSE 8001

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --log-level info"]
