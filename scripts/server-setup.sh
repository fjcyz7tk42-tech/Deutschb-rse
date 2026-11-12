#!/usr/bin/env bash
# Prepares a Linux server (e.g. the JAIF build-days machine) and starts the public stack.
#
#   On the server (web terminal is fine):
#     bash <(curl -fsSL https://raw.githubusercontent.com/fjcyz7tk42-tech/Deutschb-rse/issuer-intelligence-hub/scripts/server-setup.sh)
#   or from an existing clone:
#     bash scripts/server-setup.sh
#
# Steps: Docker + Compose 2.24.4+, clone/update the repo, create .env, check the seed, start one of
#   DEPLOY_MODE=http    plain HTTP on port 80, no domain (JAIF: public port 41080 -> 80)
#   DEPLOY_MODE=caddy   HTTPS with Let's Encrypt for APP_DOMAIN; needs public ports 80/443 and DNS
#   DEPLOY_MODE=tunnel  HTTPS through a Cloudflare Tunnel (TUNNEL_TOKEN), no open ports
# The site is protected by BASIC_AUTH_USER/BASIC_AUTH_PASSWORD from .env (the exchange data must not be public).
# Safe to run again: it pulls the branch and rebuilds the stack.
# The Parquet seed is not in git; copy it first (see the message the script prints).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/fjcyz7tk42-tech/Deutschb-rse.git}"
BRANCH="${BRANCH:-issuer-intelligence-hub}"
# /srv is the large data disk on the JAIF machines; the home directory sits on the small system disk
if [ -z "${APP_DIR:-}" ]; then
  if [ -d /srv ]; then APP_DIR=/srv/issuer-hub; else APP_DIR="$HOME/issuer-hub"; fi
fi
SEED_DIR="hub/data/reference/seed"

say()  { printf '\n==> %s\n' "$*"; }
warn() { printf '\n!!  %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
ask()  { local a; read -rp "$1" a </dev/tty || true; printf '%s' "$a"; }

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"

# --- 1. git, curl, Docker, Compose ------------------------------------------------------
need_pkgs=()
command -v git  >/dev/null 2>&1 || need_pkgs+=(git)
command -v curl >/dev/null 2>&1 || need_pkgs+=(curl)
if [ ${#need_pkgs[@]} -gt 0 ]; then
  command -v apt-get >/dev/null 2>&1 || die "please install: ${need_pkgs[*]}"
  say "Installing ${need_pkgs[*]}"
  $SUDO apt-get update -qq && $SUDO apt-get install -y -qq "${need_pkgs[@]}"
fi

if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker (get.docker.com)"
  curl -fsSL https://get.docker.com | $SUDO sh
fi

DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
  $SUDO systemctl start docker 2>/dev/null || true
  $SUDO docker info >/dev/null 2>&1 || die "Docker is installed but not running (try: $SUDO systemctl start docker)"
  if [ -n "$SUDO" ]; then DOCKER=(sudo docker); fi
fi

ver="$("${DOCKER[@]}" compose version --short 2>/dev/null || true)"
ver="${ver#v}"
[ -n "$ver" ] || die "Docker Compose plugin missing (try: curl -fsSL https://get.docker.com | $SUDO sh)"
if [ "$(printf '%s\n%s\n' 2.24.4 "$ver" | sort -V | head -1)" != "2.24.4" ]; then
  die "Docker Compose $ver is too old; the HTTPS overlay needs 2.24.4+ (try: curl -fsSL https://get.docker.com | $SUDO sh)"
fi
say "Docker Compose $ver"

# --- 2. Repository ----------------------------------------------------------------------
if [ ! -d "$APP_DIR" ] && ! mkdir -p "$APP_DIR" 2>/dev/null; then
  $SUDO mkdir -p "$APP_DIR"
  $SUDO chown "$(id -un):$(id -gn)" "$APP_DIR"
fi
if [ -d "$APP_DIR/.git" ]; then
  say "Updating $APP_DIR ($BRANCH)"
  git -C "$APP_DIR" fetch -q origin "$BRANCH"
  git -C "$APP_DIR" checkout -q "$BRANCH"
  git -C "$APP_DIR" pull -q --ff-only origin "$BRANCH"
else
  say "Cloning $REPO_URL ($BRANCH) into $APP_DIR"
  if [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
    # the seed may already be there (copied before the first run): clone next to it
    git -C "$APP_DIR" init -q
    git -C "$APP_DIR" remote add origin "$REPO_URL"
    git -C "$APP_DIR" fetch -q origin "$BRANCH"
    git -C "$APP_DIR" checkout -q -b "$BRANCH" --track "origin/$BRANCH"
  else
    git clone -q --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
fi
cd "$APP_DIR"

# --- 3. .env ----------------------------------------------------------------------------
if [ ! -f .env ]; then
  say "Creating .env"
  cp .env.example .env
  chmod 600 .env
  # Without SMTP_HOST the alert mails stay in the internal Mailpit container.
  sed -i -E 's/^(SMTP_[A-Z_]+=)/# \1/' .env
  # KEY='value' (single quotes: Docker Compose takes $ and other characters literally)
  setenv() {
    local tmp; tmp="$(mktemp)"
    grep -vE "^$1=" .env > "$tmp" || true
    printf "%s='%s'\n" "$1" "$2" >> "$tmp"
    cat "$tmp" > .env; rm -f "$tmp"
  }
  mode="$(ask 'Public access: [h]ttp on port 80 without domain (JAIF server), [c]addy HTTPS, [t]unnel? [h]: ')"
  case "$mode" in c*) mode=caddy ;; t*) mode=tunnel ;; *) mode=http ;; esac
  setenv DEPLOY_MODE "$mode"
  if [ "$mode" = http ]; then
    ip="$(curl -fsS4 --max-time 5 https://api.ipify.org 2>/dev/null || echo '<server-ip>')"
    url="$(ask "Address the browser uses, for mail links (JAIF: http://$ip:41080) [http://$ip]: ")"
    setenv PUBLIC_URL "${url:-http://$ip}"
  else
    domain="$(ask 'APP_DOMAIN, bare hostname [www.justklaris.com]: ')"
    [ -n "$domain" ] && setenv APP_DOMAIN "$domain"
  fi
  if [ "$mode" = tunnel ]; then
    token="$(ask 'Cloudflare Tunnel token: ')"
    [ -n "$token" ] || die "tunnel mode needs a token (Cloudflare Zero Trust -> Networks -> Tunnels)"
    setenv TUNNEL_TOKEN "$token"
  fi
  key="$(ask 'LLM API key for the impact card (empty = template text): ')"
  [ -n "$key" ] && setenv DEEPSEEK_API_KEY "$key"
  pw="$(ask 'Site password for user "team" (empty = generate one): ')"
  if [ -z "$pw" ]; then
    pw="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16 || true)"
    say "Generated site password: $pw   (user: team; also in $APP_DIR/.env)"
  fi
  case "$pw" in *:*|*\'*) die "the site password must not contain : or '" ;; esac
  setenv BASIC_AUTH_USER team
  setenv BASIC_AUTH_PASSWORD "$pw"
else
  say ".env exists, keeping it"
fi
envget() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -E "s/^'(.*)'\$/\\1/; s/^\"(.*)\"\$/\\1/" || true; }
domain="$(envget APP_DOMAIN)"
domain="${domain:-www.justklaris.com}"
MODE="$(envget DEPLOY_MODE)"
if [ -z "$MODE" ]; then
  # .env from before DEPLOY_MODE existed
  if [ -n "$(envget TUNNEL_TOKEN)" ]; then MODE=tunnel; else MODE=caddy; fi
fi
case "$MODE" in
  http)   COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.http.yml);   PORTS='80' ;;
  caddy)  COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.https.yml);  PORTS='80|443' ;;
  tunnel) COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.tunnel.yml); PORTS='' ;;
  *) die "DEPLOY_MODE in .env must be http, caddy or tunnel (is: $MODE)" ;;
esac
say "Mode: $MODE"
if [ -z "$(envget BASIC_AUTH_USER)" ] || [ -z "$(envget BASIC_AUTH_PASSWORD)" ]; then
  warn "No BASIC_AUTH_USER/BASIC_AUTH_PASSWORD in .env: the app and its exchange data will be open to anyone."
  [ "$(ask 'Start without a password? [y/N] ')" = "y" ] || exit 1
fi

# --- 4. Seed ----------------------------------------------------------------------------
mkdir -p "$SEED_DIR"
n_seed="$(find "$SEED_DIR" -maxdepth 1 -name '*.parquet' | wc -l | tr -d ' ')"
if [ "$n_seed" -eq 0 ]; then
  die "no seed in $APP_DIR/$SEED_DIR (it is not in git). From the laptop:
    rsync -az -e 'ssh -p <ssh-port>' hub/data/reference/seed/ $(id -un)@<server>:$APP_DIR/$SEED_DIR/
then run this script again."
fi
say "Seed: $n_seed Parquet files"

# --- 5. DNS (Caddy only) and ports (Caddy, http) ----------------------------------------
if [ "$MODE" = caddy ]; then
public_ip="$(curl -fsS4 --max-time 5 https://api.ipify.org 2>/dev/null || true)"
dns_ips="$(getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"
say "Domain $domain -> ${dns_ips:-<no A record>}; this server: ${public_ip:-<unknown>}"
if [ -z "$public_ip" ] || ! printf ' %s ' "$dns_ips" | grep -q " $public_ip "; then
  warn "The A record of $domain does not point to this server's public IP.
    Caddy cannot get a Let's Encrypt certificate until it does (it keeps retrying on its own)."
  [ "$(ask 'Start anyway? [y/N] ')" = "y" ] || exit 1
fi
fi

if [ -n "$PORTS" ]; then
  if command -v ss >/dev/null 2>&1 && ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]($PORTS)\$"; then
    if ! "${DOCKER[@]}" ps --format '{{.Names}}' | grep -Eq '^issuer-hub-(caddy|frontend)'; then
      warn "Port $PORTS is already in use on this host:"
      $SUDO ss -ltnp 2>/dev/null | grep -E "[:.]($PORTS)\s" >&2 || true
      die "free the port (or merge docker/Caddyfile into the existing proxy, see README)"
    fi
  fi

  if command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q '^Status: active'; then
    say "Opening $PORTS in ufw"
    $SUDO ufw allow 80/tcp >/dev/null
    if [ "$MODE" = caddy ]; then
      $SUDO ufw allow 443/tcp >/dev/null
      $SUDO ufw allow 443/udp >/dev/null
    fi
  fi
fi

# --- 6. Start ---------------------------------------------------------------------------
say "Building and starting the stack (first build takes a few minutes)"
"${DOCKER[@]}" compose "${COMPOSE_FILES[@]}" up --build -d
"${DOCKER[@]}" compose "${COMPOSE_FILES[@]}" ps

case "$MODE" in
  tunnel) logsvc=cloudflared; app="https://$domain" ;;
  caddy)  logsvc=caddy;       app="https://$domain" ;;
  http)   logsvc=frontend;    app="$(envget PUBLIC_URL)"
          [ "$app" = "http://localhost:8080" ] && warn "PUBLIC_URL in .env is still http://localhost:8080; mail links will not work from outside." ;;
esac
say "Done. App: $app   (user: $(envget BASIC_AUTH_USER))
    Status:       ${DOCKER[*]} compose ${COMPOSE_FILES[*]} logs --tail=50 $logsvc
    Update later: bash $APP_DIR/scripts/server-setup.sh"
if [ "$MODE" = http ]; then
  echo "    Mailpit:      ssh -p <ssh-port> -L 8025:localhost:8025 $(id -un)@<server>, then http://localhost:8025"
fi
