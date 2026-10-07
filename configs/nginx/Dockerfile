ARG NODE_IMAGE=node:24-alpine
ARG NGINX_IMAGE=nginx:stable-alpine
FROM ${NODE_IMAGE} AS frontend
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
ARG NPM_CONFIG_FETCH_RETRIES=5
ARG NPM_CONFIG_FETCH_TIMEOUT=300000
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci \
    --registry "${NPM_CONFIG_REGISTRY}" \
    --fetch-retries "${NPM_CONFIG_FETCH_RETRIES}" \
    --fetch-timeout "${NPM_CONFIG_FETCH_TIMEOUT}"
COPY frontend/ ./
RUN npm run build
FROM ${NGINX_IMAGE}
COPY --from=frontend /build/dist /usr/share/nginx/html
COPY configs/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY configs/nginx/api-proxy.conf /etc/nginx/snippets/api-proxy.conf
