# Деплой Detailing.Visual

```
Пользователь ──HTTPS──▶ основной сервер (Россия)
                          nginx (HTTPS) → web → api
                          postgres, redis, worker, xray-client
                          S3 (Россия)
                             │ только запросы воркера к Gemini
                             ▼
                 узел-1 (страна A) ┐  Xray VLESS+Reality,
                 узел-2 (страна B) ┘  автопереключение
                             │
                             ▼
                         Gemini API
```

Пользователи и данные — в России. За границу уходит только воркер, только к
`*.googleapis.com`, только через узлы. Если оба узла лежат, запрос не уходит
напрямую: генерация завершается ошибкой и возвращается на баланс.

## Что нужно

| Что | Требования |
|---|---|
| Основной VPS (Россия) | Ubuntu 24.04, 2 vCPU, 4 ГБ RAM, 40+ ГБ диска |
| 2 узла (за границей) | Ubuntu 24.04 или Debian 12, 1 vCPU, 1 ГБ, свой IPv4. Разные хостеры, разные страны, обе страны — из [списка Gemini API](https://ai.google.dev/available_regions) |
| Домен | A-запись на основной VPS |
| S3-бакет в России | приватный, у того же провайдера, что VPS |

Ниже `DOMAIN` — ваш домен, `SERVER` — IP основного VPS, `NODE1`/`NODE2` — IP узлов.

---

## 1. DNS

У регистратора домена: A-запись `DOMAIN → SERVER` и A-запись `www.DOMAIN → SERVER`.
Проверка (может занять до часа): `nslookup DOMAIN`.

## 2. Узлы (на каждом из двух, ~5 минут)

С вашего компьютера (из папки проекта):

```bash
scp deploy/xray/install-node.sh root@NODE1:/root/
ssh root@NODE1 "bash /root/install-node.sh --name node-1"
```

Скрипт ставит Xray, генерирует ключи, поднимает службу и файрвол (SSH + 443)
и в конце печатает данные узла. Они же лежат на узле в `/root/xray-node-info.txt`.
Повторить для `NODE2` с `--name node-2`.

## 3. Основной сервер: подготовка

```bash
ssh root@SERVER
apt update && apt -y upgrade
apt -y install git nginx certbot python3-certbot-nginx ufw
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

# Docker
curl -fsSL https://get.docker.com | sh
docker run --rm hello-world
```

Если `hello-world` не скачивается (Docker Hub недоступен из России), включить
зеркала и повторить:

```bash
cat >/etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://dockerhub.timeweb.cloud",
    "https://mirror.gcr.io",
    "https://cr.yandex/mirror"
  ]
}
JSON
systemctl restart docker && docker run --rm hello-world
```

Код:

```bash
git clone https://github.com/noskovde2015-byte/Detailing-Visual.git /opt/detailing
cd /opt/detailing
```

## 4. Клиент Xray

```bash
cp deploy/xray/client.example.json deploy/xray/client.json
chmod 600 deploy/xray/client.json
nano deploy/xray/client.json
```

Заменить `NODE1_*` и `NODE2_*` данными из шага 2:

| В шаблоне | Из вывода скрипта |
|---|---|
| `NODE1_IP` | `address` |
| `NODE1_UUID` | `id` (пользователь **server**, не личная ссылка) |
| `NODE1_SNI` | `serverName` |
| `NODE1_PUBLIC_KEY` | `publicKey` |
| `NODE1_SHORT_ID` | `shortId` |

## 5. S3

В консоли провайдера: создать **приватный** бакет и ключ доступа (для Yandex
Cloud — сервисный аккаунт с ролью `storage.editor` и статический ключ).

## 6. `.env`

```bash
cp deploy/env.production.example .env
chmod 600 .env
openssl rand -hex 32   # → APP_CONFIG__AUTH__SECRET_KEY
openssl rand -hex 24   # → POSTGRES_PASSWORD
nano .env
```

Заполнить домен (3 строки), секреты, ключ Gemini, S3, `S3_HOST`.

## 7. Google OAuth

В Google Cloud Console, где создан OAuth-клиент для входа на сайт
(«APIs & Services → Credentials → ваш OAuth client»):

- Authorized redirect URIs: `https://DOMAIN/api/auth/google/callback`
- Authorized JavaScript origins: `https://DOMAIN`

Если этот клиент живёт в том же Google-аккаунте, что и оплата Gemini, — заходить
только через VPN.

## 8. Запуск

```bash
docker compose up -d --build
docker compose ps
```

Все сервисы `running`/`healthy`, `migrate` — `exited (0)`. Первая сборка ~5–10 минут.

Проверка пути к Gemini — должна быть страна узла, **не RU**:

```bash
docker compose exec worker python -c "import httpx; print(httpx.get('https://ipinfo.io/country').text)"
```

## 9. HTTPS

Вместо `example.ru` — ваш домен (в обеих командах):

```bash
sed "s/DOMAIN/example.ru/g" deploy/nginx/detailing.conf > /etc/nginx/sites-available/detailing.conf
ln -s /etc/nginx/sites-available/detailing.conf /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d example.ru -d www.example.ru --redirect -m ВАША_ПОЧТА --agree-tos
```

Открыть `https://DOMAIN` и войти через Google.

## 10. Админ

```bash
docker compose exec postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB'
```

```sql
update users set is_admin = true where email = 'ваша@почта';
\q
```

Обновить страницу → «Админка» → начислить себе генерации.

## 11. Бэкапы базы

```bash
crontab -e
```

```
30 3 * * * bash /opt/detailing/deploy/backup/pg-backup.sh >> /var/log/detailing-backup.log 2>&1
```

Дампы — в `/var/backups/detailing`, хранятся 14 дней. Проверить, что работает:
`bash /opt/detailing/deploy/backup/pg-backup.sh` вручную.

Восстановление — при остановленных API и воркере, чтобы в базу никто не писал:

```bash
docker compose stop api worker
docker compose exec -T postgres sh -c 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists' < /var/backups/detailing/db-ДАТА.dump
docker compose start api worker
```

Копия на том же сервере не спасёт, если пропадёт сервер: со временем настроить
`rclone` на отдельный бакет и задать `RCLONE_REMOTE` (см. скрипт).

## 12. Личный VPN для AI Studio

В выводе скрипта узла есть ссылка `vless://…` (пользователь **personal**).
Импортировать в v2RayTun → режим «Туннель», «Всё через VPN». Google видит тот же
IP, что и у сервера; аккаунт Gemini открывать только так.

---

## Обновление

```bash
cd /opt/detailing
git pull
docker compose up -d --build
```

Воркер при остановке доделывает текущие генерации (до 9 минут), поэтому
перезапуск может занять время — это нормально.

## Если что-то не так

| Симптом | Где смотреть |
|---|---|
| Генерации падают | `docker compose logs -f worker` |
| Нет связи с узлами | `docker compose logs xray-client`, на узле `systemctl status xray`, `journalctl -u xray -n 50` |
| Сайт не открывается | `docker compose ps`, `docker compose logs web api`, `nginx -t`, `journalctl -u nginx` |
| Ошибка входа через Google | redirect URI в Google Console и `APP_CONFIG__GOOGLE__REDIRECT_URI` совпадают символ в символ |

**Узел заблокировали или он умер.** Генерации продолжают идти через второй.
Заменить: новый VPS → шаг 2 → новые данные в `deploy/xray/client.json` →
`docker compose restart xray-client`.
