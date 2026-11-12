#!/bin/sh
# Optional password for the whole site: BASIC_AUTH_USER and BASIC_AUTH_PASSWORD (from .env) turn on HTTP basic auth.
# Without them nginx serves the app openly (local development). Runs from the nginx image's /docker-entrypoint.d/.
set -eu
dir=/etc/nginx/auth.d
mkdir -p "$dir"
rm -f "$dir"/*
if [ -n "${BASIC_AUTH_USER:-}" ] && [ -n "${BASIC_AUTH_PASSWORD:-}" ]; then
  # nginx ends the password at a colon; refuse instead of starting with a password nobody can enter
  case "$BASIC_AUTH_USER$BASIC_AUTH_PASSWORD" in
    *:*) echo "basic-auth: BASIC_AUTH_USER and BASIC_AUTH_PASSWORD must not contain ':'" >&2; exit 1 ;;
  esac
  printf '%s:{PLAIN}%s\n' "$BASIC_AUTH_USER" "$BASIC_AUTH_PASSWORD" > "$dir/htpasswd"
  chown root:nginx "$dir/htpasswd"
  chmod 640 "$dir/htpasswd"
  printf 'auth_basic "IssuerLens";\nauth_basic_user_file %s/htpasswd;\n' "$dir" > "$dir/auth.conf"
  echo "basic-auth: on (user $BASIC_AUTH_USER)"
else
  echo "basic-auth: off (set BASIC_AUTH_USER and BASIC_AUTH_PASSWORD in .env to protect the site)"
fi
