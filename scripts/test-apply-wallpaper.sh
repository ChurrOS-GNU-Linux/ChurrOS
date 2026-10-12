#!/usr/bin/env bash
# Con Noctalia en marcha, un fallo transitorio de `wallpaper-set` no puede
# arrancar swaybg. Sin Noctalia, swaybg sigue siendo el backend.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
script="$root/archiso/airootfs/usr/bin/churros-apply-wallpaper"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/bin" "$tmp/runtime"
img="$tmp/wall.png"
printf 'x' >"$img"
SOCK="$tmp/runtime/wayland-9" python3 - <<'PY'
import os, socket
path = os.environ["SOCK"]
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.bind(path)
sock.listen(1)
sock.close()
PY

cat >"$tmp/bin/noctalia" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
count_file="${CHURROS_TEST_NOCTALIA_COUNT:?}"
n=0
if [[ -f "$count_file" ]]; then
    n="$(cat "$count_file")"
fi
n=$((n + 1))
printf '%s\n' "$n" >"$count_file"
if [[ "$n" -ge "${CHURROS_TEST_NOCTALIA_SUCCEED_ON:-1}" ]]; then
    exit 0
fi
echo "read() failed: Resource temporarily unavailable" >&2
exit 1
EOF

cat >"$tmp/bin/pgrep" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${CHURROS_TEST_NOCTALIA_RUNNING:-0}" != 1 ]]; then
    exit 1
fi
for arg in "$@"; do
    if [[ "$arg" == noctalia ]]; then
        exit 0
    fi
done
exit 1
EOF

cat >"$tmp/bin/swaybg" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'started\n' >>"${CHURROS_TEST_SWAYBG_LOG:?}"
sleep 5
EOF

cat >"$tmp/bin/pkill" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

chmod +x "$tmp/bin/noctalia" "$tmp/bin/pgrep" "$tmp/bin/swaybg" "$tmp/bin/pkill"

count="$tmp/count"
sway_log="$tmp/swaybg.log"

run_apply() {
    env -u XDG_CURRENT_DESKTOP -u XDG_SESSION_DESKTOP \
        PATH="$tmp/bin:$PATH" \
        XDG_RUNTIME_DIR="$tmp/runtime" \
        WAYLAND_DISPLAY="wayland-9" \
        CHURROS_TEST_NOCTALIA_COUNT="$count" \
        CHURROS_TEST_NOCTALIA_SUCCEED_ON="$1" \
        CHURROS_TEST_NOCTALIA_RUNNING="$2" \
        CHURROS_TEST_SWAYBG_LOG="$sway_log" \
        "$script" "$img"
}

fail() {
    printf 'test-apply-wallpaper: %s\n' "$1" >&2
    exit 1
}

# Argumento vacío: el script imprime el error y no sale con 0.
set +e
empty_err="$(
    env -u XDG_CURRENT_DESKTOP -u XDG_SESSION_DESKTOP \
        PATH="$tmp/bin:$PATH" \
        HOME="$tmp" \
        XDG_CONFIG_HOME="$tmp/cfg" \
        "$script" "" 2>&1
)"
empty_rc=$?
set -e
[[ "$empty_rc" -ne 0 ]] || fail "ruta vacia salio con rc=0"
[[ "$empty_err" == *"archivo no existe"* ]] || fail "ruta vacia no imprimio el error: $empty_err"

# Tres intentos: los dos primeros fallan, el tercero aplica. swaybg quieto.
: >"$count"
: >"$sway_log"
set +e
run_apply 3 1
rc=$?
set -e
[[ "$rc" -eq 0 ]] || fail "un wallpaper-set que acaba bien salio con rc=$rc"
[[ "$(cat "$count")" == 3 ]] || fail "se esperaban 3 intentos de IPC, hubo $(cat "$count")"
[[ ! -s "$sway_log" ]] || fail "swaybg arranco aunque Noctalia aplico el fondo"

# Los tres intentos fallan: error, y tampoco swaybg.
: >"$count"
: >"$sway_log"
set +e
run_apply 99 1
rc=$?
set -e
[[ "$rc" -ne 0 ]] || fail "tres fallos de IPC tendrian que devolver error"
[[ "$(cat "$count")" == 3 ]] || fail "se esperaban 3 intentos fallidos, hubo $(cat "$count")"
[[ ! -s "$sway_log" ]] || fail "swaybg arranco con Noctalia en marcha"

# Sin Noctalia, swaybg sigue disponible.
calls_before="$(cat "$count")"
: >"$sway_log"
set +e
run_apply 1 0
rc=$?
set -e
[[ "$rc" -eq 0 ]] || fail "sin Noctalia, swaybg tendria que aplicar el fondo (rc=$rc)"
[[ "$(cat "$count")" == "$calls_before" ]] || fail "sin Noctalia no habia que llamar al IPC"
[[ -s "$sway_log" ]] || fail "sin Noctalia no arranco swaybg"

printf 'ok\n'
