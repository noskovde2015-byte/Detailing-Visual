# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=22

# ---------- сборка ----------
FROM node:${NODE_VERSION}-alpine AS build

WORKDIR /app
# Сначала только манифесты: слой с node_modules пересобирается лишь при смене
# зависимостей, а не при каждой правке кода.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY . .
# Та же команда, что в CI: проверка типов + сборка Vite в dist/.
RUN npm run build


# ---------- раздача ----------
# Вариант nginx без root: слушает 8080 и работает от пользователя nginx (uid 101).
FROM nginxinc/nginx-unprivileged:1.30-alpine AS runtime

# Куда проксировать /api и чем резолвить имя. Значения по умолчанию — для
# compose (сервис api, встроенный DNS Docker); на другом хосте переопределяются.
ENV API_UPSTREAM=api:8000 \
    NGINX_RESOLVER=127.0.0.11

COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
# Шаблон заменяет стандартный default.conf образа при старте контейнера.
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1
