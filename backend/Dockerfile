ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120
ARG PIP_RETRIES=10
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV RUFF_CACHE_DIR=/tmp/ruff PYTEST_ADDOPTS="-p no:cacheprovider"
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    --timeout "${PIP_DEFAULT_TIMEOUT}" \
    --retries "${PIP_RETRIES}" \
    -r requirements.txt
COPY backend/ .
RUN useradd --uid 10001 --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips","*"]
