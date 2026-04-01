# October CMS 4.x deployment analysis

## Sources fetched
- Installation: https://docs.octobercms.com/4.x/setup/installation.html#minimum-system-requirements
- Web server config: https://docs.octobercms.com/4.x/setup/web-server-config.html
- Database config: https://docs.octobercms.com/4.x/setup/database-config.html
- Repository README: https://raw.githubusercontent.com/octobercms/october/develop/README.md

## Official requirements extracted
- PHP 8.2+
- Composer 2+
- PHP extensions: PDO, cURL, OpenSSL, Mbstring, ZipArchive, GD, SimpleXML
- Supported DB: MySQL 5.7+ or MariaDB 10.2+, PostgreSQL 9.6+, SQLite 3.8.8+
- Official install flow:
  1. `composer create-project october/october myoctober`
  2. `cd myoctober`
  3. `php artisan october:install`
  4. `php artisan october:migrate`
- Production web serving guidance:
  - create public mirror using `php artisan october:mirror`
  - point web server document root to `public`
  - disable debug and enable caches
  - run `php artisan october:optimize`
  - run `composer dump-autoload --optimize`
- DB note for older MySQL/MariaDB: set `'varcharmax' => 191` under `connections.mysql` if index length issue occurs.

## Deployment interpretation
To automate deployment robustly on this host while preserving the official install flow, use Docker Compose with three services:
- `app`: custom PHP 8.2 FPM image including required PHP extensions and Composer
- `web`: Nginx serving the mirrored `public/` directory
- `db`: MariaDB 10.11 with healthcheck

This preserves official commands while executing them inside containers:
- `composer create-project` runs in the PHP/Composer container into the mounted project path
- `php artisan october:install` runs in the app container after `.env` is prepared and DB is healthy
- `php artisan october:migrate`, `october:mirror`, `october:optimize`, and `composer dump-autoload --optimize` run in the app container

## Important automation detail
The official docs require the license key during installation but do not document non-interactive flags on the fetched page. Therefore the plan includes a discovery step to inspect local artisan help after project creation (`php artisan october:install --help`) before finalizing the exact unattended invocation. This avoids hallucinating unsupported flags while still automating the deployment.

## Target deployment shape
- Project root: `/home/eric/.openclaw/share-cep-agent/octobercms/project`
- Public HTTP port: 8080
- DB port exposed only if needed; internal service DNS preferred
- Database: `octobercms`
- App URL can later be set to target domain; for first pass use local HTTP endpoint

## Files to generate
- `docker-compose.yml`
- `docker/app/Dockerfile`
- `docker/nginx/default.conf`
- `.env`
- mirrored `public/` directory via artisan command

## Risk notes
- Installation may pause when pasting license key; docs note pressing Enter can continue.
- If installer cannot run non-interactively, ExecAgent should complete the install in PTY using the provided license key.
- If MySQL index length error appears, patch `config/database.php` with `varcharmax => 191`.
