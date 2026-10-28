#!/usr/bin/env bash
# Установка выходного узла Xray (VLESS + Reality) на зарубежный VPS.
#
# Узел только пересылает зашифрованный трафик воркера к Gemini: на нём нет
# ни сайта, ни данных. Запускается один раз на чистом Ubuntu/Debian от root:
#
#   sudo bash install-node.sh --name de-1
#
# Параметры:
#   --name NAME     имя узла в выводе и ссылке (по умолчанию: hostname)
#   --sni HOST      сайт, под который маскируется трафик (по умолчанию www.microsoft.com):
#                   крупный, с TLS 1.3, доступный из России
#   --port PORT     порт (по умолчанию 443)
#   --ip ADDRESS    публичный IPv4 узла, если не определился сам
#   --force         перезаписать существующую установку (ключи сменятся!)
#
# В конце выводит блок для deploy/xray/client.json на основном сервере
# и ссылку vless:// для личного VPN-клиента (v2RayTun и т. п.).

set -Eeuo pipefail

XRAY_VERSION="26.9.30"
XRAY_SHA256_AMD64="f851110beaff16e78d643f0ccfd9524b4a44dfd59bae3e34bb52bba378f7690e"
XRAY_SHA256_ARM64="9886f077f9fd8e6713b84c377c1c7db4e53b9bfa8c276a5bd12561139522b473"

CONFIG_DIR="/usr/local/etc/xray"
CONFIG_FILE="$CONFIG_DIR/config.json"
ASSET_DIR="/usr/local/share/xray"
INFO_FILE="/root/xray-node-info.txt"

NAME="$(hostname -s)"
SNI="www.microsoft.com"
PORT=443
PUBLIC_IP=""
FORCE=0

die() { echo "Ошибка: $*" >&2; exit 1; }
log() { echo "==> $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="${2:?}"; shift 2 ;;
    --sni) SNI="${2:?}"; shift 2 ;;
    --port) PORT="${2:?}"; shift 2 ;;
    --ip) PUBLIC_IP="${2:?}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "неизвестный параметр: $1" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "запустите от root: sudo bash $0"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "порт должен быть числом"
if [[ -f "$CONFIG_FILE" && $FORCE -eq 0 ]]; then
  die "Xray уже установлен ($CONFIG_FILE). Чтобы переустановить с новыми ключами: --force"
fi

# ---------- зависимости ----------
log "Ставлю зависимости"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl unzip ca-certificates ufw openssl >/dev/null

# ---------- Xray ----------
case "$(uname -m)" in
  x86_64) ASSET="Xray-linux-64.zip"; SUM="$XRAY_SHA256_AMD64" ;;
  aarch64) ASSET="Xray-linux-arm64-v8a.zip"; SUM="$XRAY_SHA256_ARM64" ;;
  *) die "неподдерживаемая архитектура: $(uname -m)" ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "Скачиваю Xray $XRAY_VERSION и сверяю контрольную сумму"
curl -fsSL -o "$TMP/xray.zip" \
  "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${ASSET}"
echo "$SUM  $TMP/xray.zip" | sha256sum -c --quiet - || die "контрольная сумма не совпала"
unzip -q "$TMP/xray.zip" xray geoip.dat geosite.dat -d "$TMP/x"
install -m 0755 "$TMP/x/xray" /usr/local/bin/xray
install -d -m 0755 "$ASSET_DIR"
install -m 0644 "$TMP/x/geoip.dat" "$TMP/x/geosite.dat" "$ASSET_DIR/"

id -u xray >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin xray

# ---------- ключи ----------
log "Генерирую ключи"
KEYS="$(/usr/local/bin/xray x25519)"
# Формат вывода менялся между версиями: «Public key:» → «Password (PublicKey):».
PRIVATE_KEY="$(awk -F': *' '/^Private ?[Kk]ey/ {print $2}' <<<"$KEYS")"
PUBLIC_KEY="$(awk -F': *' '/Public ?[Kk]ey/ {print $2}' <<<"$KEYS")"
[[ -n "$PRIVATE_KEY" && -n "$PUBLIC_KEY" ]] || die "не разобрал вывод xray x25519: $KEYS"

# Два пользователя: сервер сайта и ваш личный VPN. Их можно отозвать по отдельности.
UUID_SERVER="$(/usr/local/bin/xray uuid)"
UUID_PERSONAL="$(/usr/local/bin/xray uuid)"
SHORT_ID="$(openssl rand -hex 8)"

if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP="$(curl -4fsS --max-time 10 https://api.ipify.org || true)"
fi
[[ -n "$PUBLIC_IP" ]] || die "не определил публичный IP, передайте --ip"

# ---------- конфиг ----------
log "Пишу конфиг $CONFIG_FILE"
install -d -m 0750 -o root -g xray "$CONFIG_DIR"
cat >"$CONFIG_FILE" <<JSON
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "tag": "vless-in",
      "listen": "0.0.0.0",
      "port": $PORT,
      "protocol": "vless",
      "settings": {
        "clients": [
          { "id": "$UUID_SERVER", "flow": "xtls-rprx-vision", "email": "server" },
          { "id": "$UUID_PERSONAL", "flow": "xtls-rprx-vision", "email": "personal" }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "target": "$SNI:443",
          "xver": 0,
          "serverNames": ["$SNI"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SHORT_ID"]
        }
      },
      "sniffing": { "enabled": true, "destOverride": ["http", "tls", "quic"], "routeOnly": true }
    }
  ],
  "outbounds": [
    { "tag": "direct", "protocol": "freedom" },
    { "tag": "block", "protocol": "blackhole" }
  ],
  "routing": {
    "rules": [
      { "ip": ["geoip:private"], "outboundTag": "block" },
      { "protocol": ["bittorrent"], "outboundTag": "block" }
    ]
  }
}
JSON
chown root:xray "$CONFIG_FILE"
chmod 0640 "$CONFIG_FILE"

XRAY_LOCATION_ASSET="$ASSET_DIR" /usr/local/bin/xray run -test -c "$CONFIG_FILE" >/dev/null \
  || die "Xray не принял конфиг: xray run -test -c $CONFIG_FILE"

# ---------- служба ----------
log "Настраиваю службу systemd"
cat >/etc/systemd/system/xray.service <<UNIT
[Unit]
Description=Xray exit node
After=network-online.target
Wants=network-online.target

[Service]
User=xray
Group=xray
Environment=XRAY_LOCATION_ASSET=$ASSET_DIR
ExecStart=/usr/local/bin/xray run -c $CONFIG_FILE
Restart=on-failure
RestartSec=3
LimitNOFILE=65535
# Порт 443 без root: только право слушать низкие порты.
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now xray >/dev/null
sleep 1
systemctl is-active --quiet xray || die "служба не запустилась: journalctl -u xray -n 50"

# ---------- файрвол ----------
log "Настраиваю файрвол: SSH и порт $PORT"
# Порт SSH берём из настроек sshd, чтобы не закрыть себе доступ.
SSH_PORTS="$(sshd -T 2>/dev/null | awk '/^port / {print $2}' || true)"
for ssh_port in ${SSH_PORTS:-22}; do ufw allow "$ssh_port/tcp" >/dev/null; done
ufw allow "$PORT/tcp" >/dev/null
ufw --force enable >/dev/null

# ---------- итог ----------
LINK="vless://${UUID_PERSONAL}@${PUBLIC_IP}:${PORT}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=${SNI}&fp=chrome&pbk=${PUBLIC_KEY}&sid=${SHORT_ID}&type=tcp#${NAME}"

umask 077
cat >"$INFO_FILE" <<INFO
Узел: $NAME ($PUBLIC_IP:$PORT), Xray $XRAY_VERSION

--- Для deploy/xray/client.json на основном сервере ---
  address   : $PUBLIC_IP
  port      : $PORT
  id        : $UUID_SERVER
  serverName: $SNI
  publicKey : $PUBLIC_KEY
  shortId   : $SHORT_ID

--- Личный VPN (импорт ссылки в v2RayTun) ---
$LINK
INFO

echo
cat "$INFO_FILE"
echo
log "Готово. Эти данные сохранены в $INFO_FILE (доступен только root)."
