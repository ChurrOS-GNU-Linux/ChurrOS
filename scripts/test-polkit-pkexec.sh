#!/usr/bin/env bash
#
# test-polkit-pkexec.sh — sonda con polkitd y pkexec reales. Necesita root.
#
# scripts/test-polkit-rules.js prueba la regla con un polkit falso. Esta sonda
# usa el de verdad (duktape) para fijar lo que esa prueba da por hecho:
#   1. Qué detalles publica pkexec en org.freedesktop.policykit.exec: existen
#      `program` y `command_line`; no existen `command` ni getDetails() (#152).
#   2. 50-churros-store.rules carga sin errores.
#   3. Sus decisiones, con programas falsos en lugar de los reales: lo que es
#      YES se ejecuta sin agente; lo que es AUTH_ADMIN_KEEP pide contraseña
#      (no corre) sin llegar a la política por defecto; el resto llega a la
#      política por defecto.
#
# Para un contenedor desechable (CI): crea un usuario de prueba, escribe en
# /etc/polkit-1/rules.d y arranca su propio polkitd con --replace. No la
# ejecutes en tu sistema.
#
# Uso: sudo bash scripts/test-polkit-pkexec.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RULE="$ROOT/archiso/airootfs/etc/polkit-1/rules.d/50-churros-store.rules"
RULES_DIR=/etc/polkit-1/rules.d
PROBE_USER=churros-probe
# Programas falsos, en un directorio de root como los de verdad.
STUBS=/opt/churros-probe
STAMP=20261006-041530

FAILURES=0
POLKITD_PID=""
CREATED_USER=""
LOG=""

fail() { printf '  ✗ %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
pass() { printf '  ✓ %s\n' "$*"; }

cleanup() {
    if [ -n "$POLKITD_PID" ]; then
        kill "$POLKITD_PID" 2>/dev/null || true
    fi
    rm -f "$RULES_DIR/00-churros-probe.rules" "$RULES_DIR/50-churros-store.rules" \
        "$RULES_DIR/99-churros-probe.rules"
    rm -rf "$STUBS"
    if [ -n "$CREATED_USER" ]; then
        userdel "$PROBE_USER" 2>/dev/null || true
    fi
    if [ -n "$LOG" ]; then
        rm -f "$LOG"
    fi
}

if [ "$(id -u)" -ne 0 ]; then
    echo "test-polkit-pkexec: necesita root (y mejor un contenedor desechable)" >&2
    exit 2
fi

POLKITD=""
for candidate in /usr/lib/polkit-1/polkitd /usr/libexec/polkitd /usr/lib/polkit/polkitd; do
    if [ -x "$candidate" ]; then
        POLKITD="$candidate"
        break
    fi
done
for tool in pkexec runuser useradd dbus-send; do
    command -v "$tool" >/dev/null 2>&1 || { echo "test-polkit-pkexec: falta $tool" >&2; exit 2; }
done
[ -n "$POLKITD" ] || { echo "test-polkit-pkexec: falta polkitd" >&2; exit 2; }

trap cleanup EXIT
LOG="$(mktemp /tmp/churros-polkitd.XXXXXX)"

# ------------------------------------------------------------- preparación

# Bus del sistema: en un contenedor sin systemd no hay ninguno.
if [ ! -S /run/dbus/system_bus_socket ]; then
    mkdir -p /run/dbus
    if command -v dbus-uuidgen >/dev/null 2>&1; then
        dbus-uuidgen --ensure=/etc/machine-id
    fi
    dbus-daemon --system --fork
fi

getent group wheel >/dev/null || groupadd wheel
if ! id "$PROBE_USER" >/dev/null 2>&1; then
    useradd -M -G wheel -s /bin/sh "$PROBE_USER"
    CREATED_USER=yes
fi

for prog in usr/bin/pacman usr/bin/flatpak usr/bin/timedatectl usr/bin/churros-update-utils \
    usr/bin/yay usr/local/bin/churros-snapshot usr/local/bin/churros-write-root-config \
    usr/local/bin/churros-theme; do
    install -D -m 0755 /dev/stdin "$STUBS/$prog" <<'EOF'
#!/bin/sh
echo "STUB-RAN $0 $*"
EOF
done
chmod -R go-w "$STUBS"

install -d -m 0755 "$RULES_DIR"
install -m 0644 /dev/stdin "$RULES_DIR/00-churros-probe.rules" <<'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.policykit.exec") {
        polkit.log("PROBE program=" + action.lookup("program") +
                   " | command_line=" + action.lookup("command_line") +
                   " | user=" + action.lookup("user") +
                   " | command=" + action.lookup("command") +
                   " | getDetails=" + typeof action.getDetails);
    }
    return polkit.Result.NOT_HANDLED;
});
EOF
install -m 0644 /dev/stdin "$RULES_DIR/99-churros-probe.rules" <<'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.policykit.exec") {
        polkit.log("UNHANDLED " + action.lookup("command_line"));
    }
    return polkit.Result.NOT_HANDLED;
});
EOF

# La regla real con dos cambios: los programas apuntan a los falsos y no se
# exige sesión local (en un contenedor no hay logind y subject.local es
# siempre false).
sed -e "s|\"/usr/bin/|\"$STUBS/usr/bin/|g" \
    -e "s|\"/usr/local/bin/|\"$STUBS/usr/local/bin/|g" \
    -e 's/!subject\.local || //' \
    "$RULE" > "$RULES_DIR/50-churros-store.rules"
chmod 0644 "$RULES_DIR/50-churros-store.rules"
if [ "$(grep -c "\"$STUBS/" "$RULES_DIR/50-churros-store.rules")" -ne 6 ] ||
   grep -q 'subject\.local' "$RULES_DIR/50-churros-store.rules"; then
    echo "test-polkit-pkexec: no se pudo adaptar la regla (¿ha cambiado su forma?)" >&2
    exit 1
fi

# Desde polkit 127 los mensajes de arranque son de nivel info y no salen por
# defecto; los errores de las reglas sí.
POLKITD_ARGS=(--replace)
if "$POLKITD" --help 2>&1 | grep -q -- '--log-level'; then
    POLKITD_ARGS+=(--log-level=info)
fi
"$POLKITD" "${POLKITD_ARGS[@]}" > "$LOG" 2>&1 &
POLKITD_PID=$!

# PID del dueño de org.freedesktop.PolicyKit1 en el bus del sistema.
polkit_owner() {
    dbus-send --system --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus \
        org.freedesktop.DBus.GetConnectionUnixProcessID string:org.freedesktop.PolicyKit1 \
        2>/dev/null | awk '/uint32/ { print $2 }'
}
for _ in $(seq 1 40); do
    [ "$(polkit_owner)" = "$POLKITD_PID" ] && break
    sleep 0.25
done
if [ "$(polkit_owner)" != "$POLKITD_PID" ]; then
    cat "$LOG" >&2
    echo "polkitd no llegó a ser org.freedesktop.PolicyKit1" >&2
    exit 1
fi

# Ejecuta pkexec como el usuario de prueba, sin agente. El shell intermedio es
# el padre de pkexec, es decir, el sujeto de polkit.
probe() {
    runuser -u "$PROBE_USER" -- sh -c 'cd / && pkexec --disable-internal-agent "$@"' sh "$@" \
        < /dev/null 2>&1
}

# Líneas que polkitd ha añadido al log desde la posición $1 (bytes).
log_since() {
    tail -c "+$(($1 + 1))" "$LOG"
}

echo "== Reglas"
# polkitd solo nombra un fichero de reglas cuando no lo puede compilar o
# ejecutar.
if grep -q "50-churros-store.rules" "$LOG"; then
    grep "50-churros-store.rules" "$LOG"
    fail "polkitd no puede cargar 50-churros-store.rules"
else
    pass "polkitd carga 50-churros-store.rules sin errores ($(grep -o 'executing [0-9]* rules' "$LOG" || echo 'sin recuento'))"
fi

# --------------------------------------------------- 1. contrato de pkexec

echo "== Detalles que publica pkexec"
before="$(stat -c %s "$LOG")"
probe /usr/bin/true --noconfirm >/dev/null || true
probe true -x "a b" >/dev/null || true
probe --user "$PROBE_USER" /usr/bin/true y >/dev/null || true
sleep 0.2
mapfile -t seen < <(log_since "$before" | grep '^PROBE ')
printf '    %s\n' "${seen[@]}"

# expect_line REGEX — alguna línea PROBE tiene que cumplirla entera.
expect_line() {
    local wanted="$1" line
    for line in "${seen[@]}"; do
        if [[ "$line" =~ ^$wanted$ ]]; then
            pass "$line"
            return 0
        fi
    done
    fail "ninguna línea cumple: $wanted"
}
expect_line 'PROBE program=/usr/bin/true \| command_line=/usr/bin/true --noconfirm \| user=root \| command=undefined \| getDetails=undefined'
# Nombre relativo: pkexec lo busca en $PATH (el directorio depende del $PATH)
# y pone la ruta absoluta en command_line; los argumentos van unidos por
# espacios, sin comillas.
expect_line 'PROBE program=/[^ ]*/true \| command_line=/[^ ]*/true -x a b \| user=root \| command=undefined \| getDetails=undefined'
expect_line "PROBE program=/usr/bin/true \\| command_line=/usr/bin/true y \\| user=$PROBE_USER \\| command=undefined \\| getDetails=undefined"

# Informativo: desde polkit 127 `program` es el realpath del ejecutable.
before="$(stat -c %s "$LOG")"
probe /bin/true z >/dev/null || true
sleep 0.2
echo "    pkexec /bin/true z -> $(log_since "$before" | grep '^PROBE ' | head -1)"

# ------------------------------------------------------- 2. decisiones

echo "== Decisiones de 50-churros-store.rules"

decide() {
    local expect="$1" before out rc unhandled ran
    shift
    before="$(stat -c %s "$LOG")"
    rc=0
    out="$(probe "$@")" || rc=$?
    sleep 0.2
    unhandled=no
    if log_since "$before" | grep -q '^UNHANDLED '; then
        unhandled=yes
    fi
    ran=no
    case "$out" in
        *STUB-RAN*) ran=yes ;;
    esac
    case "$expect:$rc:$ran:$unhandled" in
        YES:0:yes:no|KEEP:12[67]:no:no|DEFAULT:12[67]:no:yes)
            pass "$expect: $*" ;;
        *)
            fail "$expect: $* (rc=$rc, ejecutado=$ran, política por defecto=$unhandled): $out" ;;
    esac
}

S="$STUBS/usr/bin"
L="$STUBS/usr/local/bin"
decide YES "$L/churros-snapshot" list --json
decide YES "$L/churros-snapshot" create manual
decide YES "$S/timedatectl" set-timezone America/Argentina/Buenos_Aires
decide YES "$S/timedatectl" set-ntp false
decide KEEP "$S/pacman" -Syu --noconfirm
decide KEEP "$S/flatpak" update -y
decide KEEP "$S/churros-update-utils"
decide KEEP "$L/churros-snapshot" delete "$STAMP"
decide KEEP "$L/churros-write-root-config" greetd-autologin on
decide KEEP "$L/churros-write-root-config" regreet-greeting "Hola mundo"
decide DEFAULT "$S/pacman" -Sy
decide DEFAULT "$S/pacman" -Syu --noconfirm --hookdir=/tmp/hooks
decide DEFAULT "$S/flatpak" run org.example.App
decide DEFAULT "$S/yay" -Syu
decide DEFAULT "$L/churros-theme"
decide DEFAULT "$L/churros-snapshot" list --json extra
decide DEFAULT "$S/churros-update-utils" ""
decide DEFAULT "$L/churros-write-root-config" /etc/greetd/config.toml
decide DEFAULT --user "$PROBE_USER" "$L/churros-snapshot" list --json

echo
if [ "$FAILURES" -ne 0 ]; then
    echo "test-polkit-pkexec: $FAILURES comprobaciones fallan"
    exit 1
fi
echo "test-polkit-pkexec: todo OK ($(pkexec --version))"
