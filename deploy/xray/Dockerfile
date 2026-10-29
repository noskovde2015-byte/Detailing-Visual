# syntax=docker/dockerfile:1.7

# Клиент Xray для основного сервера: принимает HTTP-прокси от воркера внутри
# сети Docker и отправляет запросы к Gemini через зарубежные узлы.
#
# Свой образ вместо готового: бинарник берётся из официального релиза на GitHub
# и сверяется с контрольной суммой — точно известно, что внутри.

FROM alpine:3.22

ARG XRAY_VERSION=26.9.30
ARG TARGETARCH
# SHA2-256 из файлов .dgst того же релиза.
ARG XRAY_SHA256_AMD64=f851110beaff16e78d643f0ccfd9524b4a44dfd59bae3e34bb52bba378f7690e
ARG XRAY_SHA256_ARM64=9886f077f9fd8e6713b84c377c1c7db4e53b9bfa8c276a5bd12561139522b473

RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
      amd64) asset=Xray-linux-64.zip; sum="$XRAY_SHA256_AMD64" ;; \
      arm64) asset=Xray-linux-arm64-v8a.zip; sum="$XRAY_SHA256_ARM64" ;; \
      *) echo "Неподдерживаемая архитектура: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    apk add --no-cache ca-certificates tzdata; \
    wget -qO /tmp/xray.zip "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${asset}"; \
    echo "$sum  /tmp/xray.zip" | sha256sum -c -; \
    mkdir -p /usr/local/share/xray; \
    unzip -q /tmp/xray.zip xray geoip.dat geosite.dat -d /tmp/xray; \
    install -m 0755 /tmp/xray/xray /usr/local/bin/xray; \
    mv /tmp/xray/geoip.dat /tmp/xray/geosite.dat /usr/local/share/xray/; \
    rm -rf /tmp/xray /tmp/xray.zip; \
    adduser -D -H -u 10001 -s /sbin/nologin xray

ENV XRAY_LOCATION_ASSET=/usr/local/share/xray

# Фиксированный uid: deploy/xray/client.json на хосте отдаётся именно ему
# (chown 10001:10001), чтобы файл с ключами мог читать только Xray и root.
USER 10001:10001

# Конфиг монтируется из deploy/xray/client.json (в git не хранится: там ключи).
ENTRYPOINT ["/usr/local/bin/xray", "run", "-c", "/etc/xray/config.json"]
