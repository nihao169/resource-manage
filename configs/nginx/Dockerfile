ARG NODE_IMAGE=node:24-alpine
ARG NGINX_IMAGE=nginx:stable-alpine
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
FROM ${NGINX_IMAGE}
COPY --from=frontend /build/dist /usr/share/nginx/html
COPY configs/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY configs/nginx/api-proxy.conf /etc/nginx/snippets/api-proxy.conf
