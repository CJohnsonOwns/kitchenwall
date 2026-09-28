#!/usr/bin/env bash
# Kitchenwall one-time setup (Docker). Run it again later to update.
#
#   curl -fsSL https://raw.githubusercontent.com/CJohnsonOwns/kitchenwall/main/install.sh | bash
#   or, from a clone:  ./install.sh
#
# It asks for a shared household password and who lives there, writes .env,
# starts the container and creates a login per person with a one-time
# password. No prompts if these are set (e.g. by an AI agent):
#   KW_PASSWORD  household password (12+ characters)
#   KW_PEOPLE    first names, space-separated, e.g. "Alex Sam" ("-" for none)
#   KW_TZ        time zone (default: this machine's)   KW_PORT  (default 8000)
#   KW_DIR       where to clone (default ./kitchenwall)
set -euo pipefail

REPO="https://github.com/CJohnsonOwns/kitchenwall.git"
say() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }
ask() {  # ask VAR "prompt" [silent]
  [ -r /dev/tty ] || die "can't ask \"$2\" without a terminal; set it in the environment (see the top of install.sh)"
  local v
  if [ "${3:-}" = silent ]; then read -rsp "$2" v </dev/tty; echo >/dev/tty; else read -rp "$2" v </dev/tty; fi
  printf -v "$1" '%s' "$v"
}
rand() { LC_ALL=C tr -dc "$1" </dev/urandom | head -c "$2" || true; }

# --- checks -----------------------------------------------------------------
command -v docker >/dev/null || die "Docker isn't installed: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "the 'docker compose' command is missing (Docker Compose v2)."
docker info >/dev/null 2>&1 || die "can't reach Docker. Run with sudo, or add yourself to the docker group."

# --- get the code -----------------------------------------------------------
if [ -f docker-compose.yml ] && [ -d app ]; then
  DIR=$PWD
else
  command -v git >/dev/null || die "git isn't installed."
  DIR=${KW_DIR:-$PWD/kitchenwall}
  [ -d "$DIR/.git" ] || git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"
OWNER="${SUDO_UID:-$(id -u)}:${SUDO_GID:-$(id -g)}"  # who owns data/ and .env (not root under sudo)

compose() { docker compose "$@"; }
wait_up() {
  for _ in $(seq 60); do
    compose exec -T kitchenwall python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=2)" \
      >/dev/null 2>&1 && return 0
    sleep 2
  done
  compose logs --tail 40 kitchenwall; die "Kitchenwall didn't start (log above)."
}

# --- already set up: just update ---------------------------------------------
if [ -f .env ]; then
  say "Already set up in $DIR: updating."
  [ -d .git ] && git pull --ff-only
  compose up -d --build
  wait_up
  say "Updated and running."
  exit 0
fi

# --- questions --------------------------------------------------------------
PW=${KW_PASSWORD:-}
while [ -z "$PW" ]; do
  ask PW "Shared household password (12+ characters, for the wall screen): " silent
  ask PW2 "Again: " silent
  [ "$PW" = "$PW2" ] || { echo "They didn't match."; PW=; }
done
[ ${#PW} -ge 12 ] || die "the household password needs at least 12 characters."
case $PW in *"'"*|*$'\n'*) die "the household password can't contain ' or a line break." ;; esac

PEOPLE=${KW_PEOPLE:-}
[ -n "$PEOPLE" ] || ask PEOPLE "Who lives here? First names separated by spaces (Enter to skip): "
[ "$PEOPLE" = "-" ] && PEOPLE=

TZONE=${KW_TZ:-$( (timedatectl show -p Timezone --value 2>/dev/null || readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||') | head -1)}
TZONE=${TZONE:-Etc/UTC}
PORT=${KW_PORT:-8000}

# --- .env + data ------------------------------------------------------------
say "Writing .env (time zone $TZONE, port $PORT)"
umask 077
cat > .env <<EOF
# Kitchenwall settings. Keep this file with data/ in your backups.
HOUSEHOLD_PASSWORD='$PW'
SESSION_SECRET=$(rand 'A-Za-z0-9' 64)

# Optional: "Sign in with Google" for Gmail (see README).
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Optional upload caps in MB (unset = no limit).
# MAX_PHOTO_MB=
# MAX_VIDEO_MB=

# Used by docker-compose.yml.
TZ=$TZONE
KW_PORT=$PORT
KW_UID=${OWNER%:*}
KW_GID=${OWNER#*:}
EOF
mkdir -p data
chown "$OWNER" .env data 2>/dev/null || true

# --- start ------------------------------------------------------------------
say "Building and starting (the first build takes a minute or two)"
compose up -d --build
wait_up

LOGINS=()
for name in $PEOPLE; do
  user=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')
  [ -n "$user" ] && [ "$user" != household ] || { echo "Skipping '$name' (use plain letters)."; continue; }
  temp=$(rand 'a-km-z2-9' 8)
  printf '%s\n' "$temp" | compose exec -T kitchenwall python deploy/add_user.py --temp "$user" "$name" >/dev/null
  LOGINS+=("$(printf '  %-14s %s' "$name" "$temp")")
done

IP=$( (hostname -I 2>/dev/null || ipconfig getifaddr en0 2>/dev/null) | awk '{print $1}')
echo
say "Kitchenwall is running: http://${IP:-this-computer}:$PORT"
echo "  Wall screen: sign in as Household with the password you chose."
if [ ${#LOGINS[@]} -gt 0 ]; then
  echo "  One-time passwords (each person picks their own on first sign-in):"
  printf '%s\n' "${LOGINS[@]}"
fi
echo "  Next: Settings -> weather location; Inbox -> Manage accounts to add Gmail."
echo "  Update later: run ./install.sh again in $DIR"
