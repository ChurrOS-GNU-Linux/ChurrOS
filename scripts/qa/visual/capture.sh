#!/usr/bin/env bash
# Arranca una ISO en QEMU y deja capturas en --out.
#
# KVM si /dev/kvm se puede abrir; si no, TCG. La sesión gráfica va por
# virgl en un Xvfb (SDL + GL, 1920x1080 por EDID): VNC y el contexto GL no
# conviven. QMP sigue abierto. Si QEMU muere tras crear el socket, se
# reintenta sin GL. Sin 3D el escritorio de niri no pinta y la captura
# queda en capture-failed. GRUB, Plymouth, el escritorio, la barra y el
# menú de sesión los toma el script. OpenCode recorre solo las pantallas
# del diff que no son esas, cuando el escritorio ya está listo. Sin
# xdotool la captura se corta: la ventana SDL no queda en 0,0.
#
# --dry-run no arranca QEMU: escribe manifest.json con el plan y el acelerador.
# --missing escribe el manifiesto sin ISO (el artefacto no llegó a tiempo).
#
# Uso:
#   capture.sh --plan plan.json --out DIR [--iso ISO] [--role before|after]
#       [--dry-run|--missing]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

iso=""
out=""
plan=""
role="before"
dry_run=0
missing=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --iso) iso="${2:?}"; shift 2 ;;
    --out) out="${2:?}"; shift 2 ;;
    --plan) plan="${2:?}"; shift 2 ;;
    --role) role="${2:?}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --missing) missing=1; shift ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "visual-qa: argumento desconocido: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$out" || -z "$plan" ]]; then
  echo "visual-qa: faltan --out y --plan" >&2
  exit 2
fi
case "$role" in
  before|after) ;;
  *) echo "visual-qa: role no admitido: $role" >&2; exit 2 ;;
esac
if [[ ! -f "$plan" ]]; then
  echo "visual-qa: no existe el plan $plan" >&2
  exit 2
fi

mkdir -p "$out"
workdir="$(mktemp -d "${TMPDIR:-/tmp}/churros-visual-capture.XXXXXX")"
qmp="$workdir/qmp.sock"
serial="$out/serial.log"
qemu_pid=""
xvfb_pid=""
vnc_display=""
vnc_note="unavailable"
firmware="bios"
agent_status="not-run"
agent_reason=""
accel="tcg"
gpu="plain"
graphical="false"
display_mode=""

cleanup() {
  if [[ -n "$qemu_pid" ]] && kill -0 "$qemu_pid" 2>/dev/null; then
    python3 "$SCRIPT_DIR/vmctl.py" quit --socket "$qmp" >/dev/null 2>&1 || kill "$qemu_pid" 2>/dev/null || true
    wait "$qemu_pid" 2>/dev/null || true
  fi
  if [[ -n "$xvfb_pid" ]] && kill -0 "$xvfb_pid" 2>/dev/null; then
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
  fi
  rm -rf "$workdir"
}
trap cleanup EXIT

if [[ -r /dev/kvm && -w /dev/kvm ]]; then
  accel="kvm"
fi
case "${VISUAL_QA_GPU:-auto}" in
  plain) gpu="plain" ;;
  virgl) gpu="virgl" ;;
  auto)
    if command -v Xvfb >/dev/null 2>&1 || [[ -e /dev/dri/renderD128 ]]; then
      gpu="virgl"
    fi
    ;;
  *)
    echo "visual-qa: VISUAL_QA_GPU no admitido" >&2
    exit 2
    ;;
esac

mapfile -t screens < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1], encoding="utf-8"))["screens"]))' "$plan")

write_manifest() {
  local status="$1"
  python3 - "$out/manifest.json" "$role" "$iso" "$accel" "$gpu" "$firmware" "$vnc_note" "$agent_status" "$agent_reason" "$status" "$plan" "$out/shots.jsonl" "$graphical" "$display_mode" <<'PY'
import json, pathlib, sys
(path, role, iso, accel, gpu, firmware, vnc, agent, agent_reason, status, plan_path, shots_path, graphical, display_mode) = sys.argv[1:]
plan = json.loads(pathlib.Path(plan_path).read_text(encoding="utf-8"))
shots = []
shot_file = pathlib.Path(shots_path)
if shot_file.is_file():
    shots = [json.loads(line) for line in shot_file.read_text(encoding="utf-8").splitlines() if line.strip()]
pathlib.Path(path).write_text(json.dumps({
    "role": role,
    "status": status,
    "iso": iso,
    "accel": accel,
    "gpu": gpu,
    "graphical": graphical == "true",
    "display": display_mode,
    "firmware": firmware,
    "vnc": vnc,
    "screens": plan.get("screens", []),
    "paths": plan.get("paths", []),
    "shots": shots,
    "agent": {"tool": "opencode", "status": agent, "reason": agent_reason},
}, indent=2) + "\n", encoding="utf-8")
PY
}

note_shot() {
  python3 - "$out/shots.jsonl" "$1" "$2" "$3" "$4" <<'PY'
import json, pathlib, sys
path, screen, ok, method, filename = sys.argv[1:]
with pathlib.Path(path).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({
        "id": screen, "ok": ok == "ok", "method": method, "file": filename,
    }) + "\n")
PY
}

if [[ "$dry_run" -eq 1 ]]; then
  agent_status="dry-run"
  agent_reason="dry-run"
  write_manifest "dry-run"
  exit 0
fi
if [[ "$missing" -eq 1 ]]; then
  agent_status="not-run"
  agent_reason="iso-missing"
  write_manifest "iso-missing"
  exit 0
fi
if [[ -z "$iso" || ! -f "$iso" ]]; then
  echo "visual-qa: falta la ISO (--iso)" >&2
  agent_status="not-run"
  agent_reason="iso-missing"
  write_manifest "iso-missing"
  exit 2
fi
if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
  echo "visual-qa: no está qemu-system-x86_64" >&2
  agent_status="not-run"
  agent_reason="qemu-missing"
  write_manifest "qemu-missing"
  exit 1
fi

vnc_display="$(python3 "$SCRIPT_DIR/vmctl.py" free-display)"
cpu="max"
if [[ "$accel" == "kvm" ]]; then
  cpu="host"
fi

launch_xvfb() {
  local info number
  command -v Xvfb >/dev/null 2>&1 || return 1
  info="$(python3 - <<'PY'
import os, subprocess, sys
read_fd, write_fd = os.pipe()
proc = subprocess.Popen(
    ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "2560x1600x24", "-nolisten", "tcp"],
    pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
os.close(write_fd)
with os.fdopen(read_fd) as handle:
    number = handle.readline().strip()
if not number:
    proc.terminate()
    sys.exit(1)
print(f"{proc.pid} {number}")
PY
)" || return 1
  xvfb_pid="${info%% *}"
  number="${info#* }"
  export DISPLAY=":${number}"
  export VISUAL_QA_XWD_DISPLAY="$DISPLAY"
  export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"
}

build_cmd() {
  local mode="$1"
  QEMU_CMD=(
    qemu-system-x86_64
    -name churros-visual-qa
    -machine "q35,accel=${accel}"
    -cpu "$cpu"
    -smp "${VISUAL_QA_QEMU_CPUS:-2}"
    -m "${VISUAL_QA_QEMU_MEM:-4096}"
    -qmp "unix:${qmp},server=on,wait=off"
    -serial "file:${serial}"
    -cdrom "$iso"
    -boot d
    -no-reboot
  )
  # VNC y virtio-vga-gl no pueden ir juntos: QEMU crea el socket QMP y
  # luego muere con "Display vnc is incompatible with the GL context".
  if [[ "$mode" == "gl" ]]; then
    QEMU_CMD+=(
      -device "virtio-vga-gl,xres=1920,yres=1080,edid=on"
      -display "sdl,gl=on"
    )
  else
    QEMU_CMD+=(
      -device "virtio-vga,xres=1920,yres=1080,edid=on"
      -vnc "127.0.0.1:${vnc_display}"
    )
  fi
  if ((${#FW[@]})); then
    QEMU_CMD+=("${FW[@]}")
  fi
}

FW=()
if fw_line="$(bash -c 'set -euo pipefail; source "$1"; churros_resolve_pflash x86_64 "$2"' bash "$ROOT/scripts/lib/ovmf.sh" "$workdir" 2>/dev/null)"; then
  code="${fw_line%% *}"
  vars_template="${fw_line#* }"
  if [[ -f "$code" && -f "$vars_template" ]]; then
    cp "$vars_template" "$workdir/vars.fd"
    FW=(
      -drive "if=pflash,format=raw,readonly=on,file=${code}"
      -drive "if=pflash,format=raw,file=${workdir}/vars.fd"
    )
    firmware="uefi"
  fi
fi

stop_qemu() {
  if [[ -n "$qemu_pid" ]] && kill -0 "$qemu_pid" 2>/dev/null; then
    kill "$qemu_pid" 2>/dev/null || true
    wait "$qemu_pid" 2>/dev/null || true
  fi
  qemu_pid=""
  rm -f "$qmp"
}

qemu_stayed_up() {
  kill -0 "$qemu_pid" 2>/dev/null || return 1
  if [[ -f "$out/qemu.log" ]] && grep -q 'incompatible with the GL context' "$out/qemu.log"; then
    return 1
  fi
  return 0
}

launch_qemu() {
  local mode="$1"
  local spins=0
  stop_qemu
  build_cmd "$mode"
  printf '%s\n' "${QEMU_CMD[*]}" >> "$out/qemu-attempts.log"
  # Sin gestor de ventanas SDL centra la ventana de GRUB y, al pasar a
  # 1920x1080, ese origen la saca de la pantalla. Queda clavada en 0,0.
  SDL_VIDEO_WINDOW_POS=0,0 "${QEMU_CMD[@]}" >"$out/qemu.log" 2>&1 &
  qemu_pid=$!
  while [[ ! -S "$qmp" ]]; do
    if ! kill -0 "$qemu_pid" 2>/dev/null; then
      qemu_pid=""
      return 1
    fi
    spins=$((spins + 1))
    if [[ "$spins" -gt 50 ]]; then
      stop_qemu
      return 1
    fi
    sleep 0.2
  done
  # El socket aparece antes de que QEMU decida morir por la pantalla.
  sleep 1
  if ! qemu_stayed_up; then
    stop_qemu
    return 1
  fi
  display_mode="$mode"
  if [[ "$mode" == "gl" ]]; then
    graphical="true"
    vnc_note="unavailable"
  else
    graphical="false"
    vnc_note="127.0.0.1:$((5900 + vnc_display))"
  fi
  return 0
}

want_gl=0
if [[ "$gpu" == "virgl" ]]; then
  if launch_xvfb; then
    want_gl=1
  else
    gpu="plain"
  fi
fi
if [[ "$want_gl" -eq 1 ]]; then
  launch_qemu gl || echo "visual-qa: GL no se mantuvo en marcha; reintento sin GL" >&2
fi
if [[ -z "$display_mode" ]]; then
  gpu="plain"
  graphical="false"
  launch_qemu plain || echo "visual-qa: el arranque sin GL tampoco se mantuvo" >&2
fi
if [[ -z "$display_mode" ]]; then
  echo "visual-qa: QEMU no se mantuvo en marcha" >&2
  agent_reason="qemu-failed"
  write_manifest "qemu-failed"
  exit 1
fi

need_grub=0
need_plymouth=0
for screen in "${screens[@]}"; do
  case "$screen" in
    grub) need_grub=1 ;;
    plymouth) need_plymouth=1 ;;
  esac
done
if [[ "$need_grub" -eq 1 || "$need_plymouth" -eq 1 ]]; then
  python3 "$SCRIPT_DIR/bootframes.py" watch \
    --socket "$qmp" --serial "$serial" --out "$out" \
    --timeout "${VISUAL_QA_BOOT_POLL:-20}" \
    --grub "$need_grub" --plymouth "$need_plymouth"
  while IFS=' ' read -r shot_id shot_ok shot_method shot_file; do
    [[ -n "$shot_id" ]] || continue
    note_shot "$shot_id" "$shot_ok" "$shot_method" "$shot_file"
  done < <(python3 -c '
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
methods = {"ok": "qmp-poll", "missed": "menu-missed", "absent": "not-in-boot"}
for key in ("grub", "plymouth"):
    value = data.get(key)
    if not value:
        continue
    print(key, "ok" if value == "ok" else "fail", methods.get(value, value), key + ".png")
' "$out/boot-watch.json")
fi

base_screens=()
diff_screens=()
for screen in "${screens[@]}"; do
  case "$screen" in
    grub|plymouth) ;;
    desktop|bar|session-menu) base_screens+=("$screen") ;;
    *) diff_screens+=("$screen") ;;
  esac
done

scrub_log() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  python3 - "$file" <<'PY'
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="replace")
for name in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
    secret = os.environ.get(name) or ""
    if secret:
        text = text.replace(secret, "[redacted]")
path.write_text(text, encoding="utf-8")
PY
}

dismiss_overlay() {
  python3 "$SCRIPT_DIR/vmctl.py" send-key --socket "$qmp" --key esc || true
  sleep "${VISUAL_QA_OVERLAY_DELAY:-2}"
  python3 "$SCRIPT_DIR/vmctl.py" send-key --socket "$qmp" --key esc || true
  sleep "${VISUAL_QA_OVERLAY_DELAY:-2}"
}

close_session_menu() {
  local tries=0 probe
  probe="$workdir/_menu-closed.png"
  while (( tries < 8 )); do
    python3 "$SCRIPT_DIR/vmctl.py" send-key --socket "$qmp" --key esc || true
    sleep 1
    if ! python3 "$SCRIPT_DIR/vmctl.py" screendump --socket "$qmp" --out "$probe"; then
      return 0
    fi
    if [[ ! -f "$base" ]]; then
      return 0
    fi
    if python3 "$SCRIPT_DIR/bootframes.py" menu-visible --before "$base" --after "$probe" >/dev/null; then
      tries=$((tries + 1))
      continue
    fi
    return 0
  done
}

park_stray_pngs() {
  local png name keep screen
  shopt -s nullglob
  for png in "$out"/*.png; do
    name="$(basename "$png" .png)"
    keep=0
    for screen in "${screens[@]}"; do
      if [[ "$name" == "$screen" ]]; then
        keep=1
        break
      fi
    done
    if [[ "$keep" -eq 0 ]]; then
      mv "$png" "$workdir/"
    fi
  done
  shopt -u nullglob
}

final_status="captured"
export VISUAL_QA_QEMU_NAME=churros-visual-qa
export VISUAL_QA_GUEST_WIDTH=1920
export VISUAL_QA_GUEST_HEIGHT=1080
desktop_ready=0
need_desktop=0
if [[ ${#base_screens[@]} -gt 0 || ${#diff_screens[@]} -gt 0 ]]; then
  need_desktop=1
fi
if [[ "$graphical" != "true" && "$need_desktop" -eq 1 ]]; then
  final_status="capture-failed"
  for screen in "${base_screens[@]}" "${diff_screens[@]}"; do
    note_shot "$screen" fail "no-graphical-session" "${screen}.png"
  done
  if [[ ${#diff_screens[@]} -gt 0 ]]; then
    agent_status="no-graphical-session"
    agent_reason="no-graphical-session"
  else
    agent_status="not-run"
    agent_reason="no-diff-screens"
  fi
  base_screens=()
  diff_screens=()
elif [[ "$need_desktop" -eq 1 ]]; then
  # En TCG el escritorio tarda unos 4-6 min. OpenCode no arranca antes.
  desktop_timeout="${VISUAL_QA_DESKTOP_TIMEOUT:-600}"
  if ! python3 "$SCRIPT_DIR/bootframes.py" wait-desktop --socket "$qmp" --timeout "$desktop_timeout"; then
    final_status="capture-failed"
    agent_status="desktop-not-ready"
    agent_reason="desktop-not-ready"
    for screen in "${base_screens[@]}" "${diff_screens[@]}"; do
      note_shot "$screen" fail "desktop-not-ready" "${screen}.png"
    done
    base_screens=()
    diff_screens=()
  else
    desktop_ready=1
  fi
fi

base="$workdir/_desktop-base.png"
menu_opened=0
if [[ "$desktop_ready" -eq 1 ]]; then
  dismiss_overlay
  if ! python3 "$SCRIPT_DIR/vmctl.py" screendump --socket "$qmp" --out "$base"; then
    rm -f "$base"
  fi
fi
if [[ ${#base_screens[@]} -gt 0 ]]; then
  if [[ ! -f "$base" ]]; then
    final_status="capture-failed"
    for screen in "${base_screens[@]}"; do
      note_shot "$screen" fail "screendump" "${screen}.png"
    done
  else
    for screen in "${base_screens[@]}"; do
      [[ "$screen" == "session-menu" ]] && continue
      cp "$base" "$out/${screen}.png"
      set +e
      reason="$(python3 "$SCRIPT_DIR/bootframes.py" assess --png "$out/${screen}.png" --width 1920 --height 1080 --require-bar)"
      assess_rc=$?
      set -e
      if [[ "$assess_rc" -eq 0 ]]; then
        note_shot "$screen" ok "$reason" "${screen}.png"
      else
        note_shot "$screen" fail "${reason:-not-graphical}" "${screen}.png"
        final_status="capture-failed"
      fi
    done
    for screen in "${base_screens[@]}"; do
      [[ "$screen" == "session-menu" ]] || continue
      menu_opened=1
      python3 "$SCRIPT_DIR/vmctl.py" send-key --socket "$qmp" --key meta_l --key shift --key e || true
      menu_timeout="${VISUAL_QA_MENU_TIMEOUT:-90}"
      menu_deadline=$((SECONDS + menu_timeout))
      menu_reason="menu-not-visible:timeout"
      menu_rc=1
      while (( SECONDS < menu_deadline )); do
        if ! python3 "$SCRIPT_DIR/vmctl.py" screendump --socket "$qmp" --out "$out/session-menu.png"; then
          menu_reason="screendump"
          menu_rc=1
          break
        fi
        set +e
        menu_reason="$(python3 "$SCRIPT_DIR/bootframes.py" menu-visible --before "$base" --after "$out/session-menu.png")"
        menu_rc=$?
        set -e
        if [[ "$menu_rc" -eq 0 ]]; then
          break
        fi
        sleep "${VISUAL_QA_MENU_POLL:-2}"
      done
      if [[ "$menu_rc" -ne 0 ]]; then
        note_shot session-menu fail "${menu_reason:-menu-not-visible}" "session-menu.png"
        final_status="capture-failed"
        continue
      fi
      set +e
      reason="$(python3 "$SCRIPT_DIR/bootframes.py" assess --png "$out/session-menu.png" --width 1920 --height 1080)"
      assess_rc=$?
      set -e
      if [[ "$assess_rc" -eq 0 ]]; then
        note_shot session-menu ok "wlogout" "session-menu.png"
      else
        note_shot session-menu fail "${reason:-not-graphical}" "session-menu.png"
        final_status="capture-failed"
      fi
    done
  fi
fi
if [[ "$menu_opened" -eq 1 ]]; then
  close_session_menu
fi
if [[ ${#diff_screens[@]} -eq 0 ]]; then
  if [[ -z "$agent_reason" ]]; then
    agent_status="not-run"
    agent_reason="no-diff-screens"
  fi
elif [[ "$desktop_ready" -eq 1 ]]; then
  prompt="$out/opencode-prompt.txt"
  python3 "$SCRIPT_DIR/prompt.py" \
    --qmp "$qmp" --vnc "$vnc_note" --out "$out" \
    --vmctl "$SCRIPT_DIR/vmctl.py" --screens "${diff_screens[@]}" > "$prompt"
  if ! command -v opencode >/dev/null 2>&1; then
    agent_status="missing"
    agent_reason="opencode-missing"
  elif [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    agent_status="not-run"
    agent_reason="no-key"
  else
    model="${VISUAL_QA_MODEL:-claude-haiku-4-5}"
    if [[ "$model" != */* ]]; then
      model="anthropic/${model}"
    fi
    help_text="$(opencode --help 2>&1 || true)"
    if ! grep -q 'run' <<<"$help_text"; then
      agent_status="unsupported-cli"
      agent_reason="unsupported-cli"
    else
      set +e
      if command -v timeout >/dev/null 2>&1; then
        timeout 600 opencode run --model "$model" "$(cat "$prompt")" >"$out/opencode.log" 2>&1
      else
        opencode run --model "$model" "$(cat "$prompt")" >"$out/opencode.log" 2>&1
      fi
      rc=$?
      set -e
      scrub_log "$out/opencode.log"
      if [[ "$rc" -eq 0 ]]; then
        agent_status="ok"
        agent_reason="ok"
      else
        agent_status="failed"
        agent_reason="failed"
      fi
    fi
  fi
  if [[ "$agent_status" == "not-run" || "$agent_status" == "missing" || "$agent_status" == "unsupported-cli" ]]; then
    for screen in "${diff_screens[@]}"; do
      note_shot "$screen" fail "not-run:${agent_reason}" "${screen}.png"
    done
    final_status="capture-failed"
  else
    missing_shot=0
    for screen in "${diff_screens[@]}"; do
      png="$out/${screen}.png"
      if [[ ! -f "$png" ]]; then
        note_shot "$screen" fail "missing" "${screen}.png"
        missing_shot=1
        continue
      fi
      set +e
      reason="$(python3 "$SCRIPT_DIR/bootframes.py" assess --png "$png" --width 1920 --height 1080)"
      assess_rc=$?
      set -e
      if [[ "$assess_rc" -ne 0 ]]; then
        note_shot "$screen" fail "${reason:-not-graphical}" "${screen}.png"
        missing_shot=1
        continue
      fi
      if [[ ! -f "$base" ]]; then
        note_shot "$screen" fail "same-as-desktop" "${screen}.png"
        missing_shot=1
        continue
      fi
      set +e
      reason="$(python3 "$SCRIPT_DIR/bootframes.py" differs --before "$base" --after "$png")"
      differ_rc=$?
      set -e
      if [[ "$differ_rc" -eq 0 ]]; then
        note_shot "$screen" ok "$reason" "${screen}.png"
      else
        note_shot "$screen" fail "${reason:-same-as-desktop}" "${screen}.png"
        missing_shot=1
      fi
    done
    if [[ "$missing_shot" -eq 1 ]]; then
      final_status="capture-failed"
      if [[ "$agent_status" == "ok" ]]; then
        agent_status="incomplete"
        agent_reason="incomplete"
      fi
    fi
  fi
fi

park_stray_pngs
write_manifest "$final_status"
echo "visual-qa: capturas en $out (agent=${agent_status}, accel=${accel}, gpu=${gpu})" >&2
