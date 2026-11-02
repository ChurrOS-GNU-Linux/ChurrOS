#!/usr/bin/env bash
# Arranca una ISO en QEMU y deja capturas en --out.
#
# KVM si /dev/kvm se puede abrir; si no, TCG. Expone VNC en 127.0.0.1 y QMP
# por un socket. GRUB y Plymouth se capturan con QMP screendump (y xwd si la
# salida es GL). El resto lo recorre OpenCode con Claude, usando vmctl.py.
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
accel="tcg"
gpu="plain"

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
  python3 - "$out/manifest.json" "$role" "$iso" "$accel" "$gpu" "$firmware" "$vnc_note" "$agent_status" "$status" "$plan" "$out/shots.jsonl" <<'PY'
import json, pathlib, sys
(path, role, iso, accel, gpu, firmware, vnc, agent, status, plan_path, shots_path) = sys.argv[1:]
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
    "firmware": firmware,
    "vnc": vnc,
    "screens": plan.get("screens", []),
    "paths": plan.get("paths", []),
    "shots": shots,
    "agent": {"tool": "opencode", "status": agent},
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
  write_manifest "dry-run"
  exit 0
fi
if [[ "$missing" -eq 1 ]]; then
  agent_status="not-run"
  write_manifest "iso-missing"
  exit 0
fi
if [[ -z "$iso" || ! -f "$iso" ]]; then
  echo "visual-qa: falta la ISO (--iso)" >&2
  write_manifest "iso-missing"
  exit 2
fi
if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
  echo "visual-qa: no está qemu-system-x86_64" >&2
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
  if [[ -e /dev/dri/renderD128 ]]; then
    return 0
  fi
  command -v Xvfb >/dev/null 2>&1 || return 1
  info="$(python3 - <<'PY'
import os, subprocess, sys
read_fd, write_fd = os.pipe()
proc = subprocess.Popen(
    ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
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
  local with_vnc="$1"
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
  if [[ "$gpu" == "virgl" ]]; then
    QEMU_CMD+=(-device "virtio-vga-gl" -display "sdl,gl=on")
    if [[ "$with_vnc" -eq 1 ]]; then
      QEMU_CMD+=(-vnc "127.0.0.1:${vnc_display}")
    fi
  elif [[ "$with_vnc" -eq 1 ]]; then
    QEMU_CMD+=(-device "virtio-vga,xres=1920,yres=1080" -vnc "127.0.0.1:${vnc_display}")
  else
    QEMU_CMD+=(-device "virtio-vga,xres=1920,yres=1080" -display none)
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

if [[ "$gpu" == "virgl" && ! -e /dev/dri/renderD128 ]]; then
  launch_xvfb || gpu="plain"
fi

launch_qemu() {
  local with_vnc="$1"
  rm -f "$qmp" "$serial"
  build_cmd "$with_vnc"
  "${QEMU_CMD[@]}" >"$out/qemu.log" 2>&1 &
  qemu_pid=$!
  local spins=0
  while [[ ! -S "$qmp" ]]; do
    if ! kill -0 "$qemu_pid" 2>/dev/null; then
      return 1
    fi
    spins=$((spins + 1))
    if [[ "$spins" -gt 50 ]]; then
      return 1
    fi
    sleep 0.2
  done
  return 0
}

if launch_qemu 1; then
  vnc_note="127.0.0.1:$((5900 + vnc_display))"
else
  echo "visual-qa: qemu rechazó VNC con esta GPU; reintento sin VNC" >&2
  if [[ -n "$qemu_pid" ]]; then
    kill "$qemu_pid" 2>/dev/null || true
    wait "$qemu_pid" 2>/dev/null || true
    qemu_pid=""
  fi
  if ! launch_qemu 0; then
    echo "visual-qa: QEMU no arrancó" >&2
    write_manifest "qemu-failed"
    exit 1
  fi
fi

shot() {
  local screen="$1" method
  if method="$(python3 "$SCRIPT_DIR/vmctl.py" screendump --socket "$qmp" --out "$out/${screen}.png")"; then
    note_shot "$screen" ok "$method" "${screen}.png"
  else
    note_shot "$screen" fail "qmp" "${screen}.png"
  fi
}

for screen in "${screens[@]}"; do
  case "$screen" in
    grub)
      sleep "${VISUAL_QA_GRUB_DELAY:-2}"
      shot grub
      ;;
    plymouth)
      python3 "$SCRIPT_DIR/vmctl.py" wait-serial --log "$serial" \
        --pattern 'Linux version|plymouth|Welcome to ChurrOS' \
        --timeout "${VISUAL_QA_BOOT_TIMEOUT:-120}" || true
      shot plymouth
      ;;
  esac
done

desktop=()
for screen in "${screens[@]}"; do
  case "$screen" in
    grub|plymouth) ;;
    *) desktop+=("$screen") ;;
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

if ((${#desktop[@]})); then
  prompt="$out/opencode-prompt.txt"
  python3 - "$prompt" "$qmp" "$vnc_note" "$out" "$SCRIPT_DIR/vmctl.py" "${desktop[@]}" <<'PY'
import pathlib, sys
prompt, qmp, vnc, out, vmctl, *screens = sys.argv[1:]
lines = [
    "Capture screenshots of a running ChurrOS live ISO. Do not print API keys or tokens.",
    f"QMP socket: {qmp}",
    f"VNC (localhost only): {vnc}",
    "Drive the VM only through this helper:",
    f"  python3 {vmctl} screendump --socket {qmp} --out {out}/NAME.png",
    f"  python3 {vmctl} send-key --socket {qmp} --key KEY [--key KEY]",
    f"  python3 {vmctl} wait-serial --log {out}/serial.log --pattern REGEX --timeout SECONDS",
    "The live user churros is logged in automatically.",
    "Shortcuts: super+spc opens the Noctalia launcher (Mod+Space).",
    "super+shift+e opens wlogout. ret confirms.",
    "Calamares is /usr/local/bin/calamares.",
    "Write exactly these files and then exit:",
]
for screen in screens:
    lines.append(f"- {out}/{screen}.png ({screen})")
pathlib.Path(prompt).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  agent_status="missing"
  if ! command -v opencode >/dev/null 2>&1; then
    agent_status="missing"
  elif [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    agent_status="no-key"
  else
    model="${VISUAL_QA_MODEL:-claude-haiku-4-5}"
    if [[ "$model" != */* ]]; then
      model="anthropic/${model}"
    fi
    help_text="$(opencode --help 2>&1 || true)"
    if ! grep -q 'run' <<<"$help_text"; then
      agent_status="unsupported-cli"
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
      else
        agent_status="failed"
      fi
    fi
  fi
  for screen in "${desktop[@]}"; do
    if [[ -f "$out/${screen}.png" ]]; then
      note_shot "$screen" ok "opencode" "${screen}.png"
    else
      note_shot "$screen" fail "opencode" "${screen}.png"
    fi
  done
fi

write_manifest "captured"
echo "visual-qa: capturas en $out (agent=${agent_status}, accel=${accel}, gpu=${gpu})" >&2
