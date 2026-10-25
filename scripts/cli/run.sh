#!/usr/bin/env bash

set -e

# shellcheck source=scripts/lib/ovmf.sh
source "$(cd "$(dirname "$0")/.." && pwd)/lib/ovmf.sh"
# shellcheck source=scripts/lib/host.sh
source "$(cd "$(dirname "$0")/.." && pwd)/lib/host.sh"

VM_DIR="vm"
# Sin --arch se usa la arquitectura del equipo, igual que ./churros build.
TARGET_ARCH=""
USE_CONTAINER=0
QEMU_BIN="qemu-system-aarch64"
DISK="$VM_DIR/ChurrOS-arm64.qcow2"
VARS="$VM_DIR/OVMF_VARS_arm64.fd"

for ((arg_index = 1; arg_index <= $#; arg_index++)); do
    arg="${!arg_index}"
    case "$arg" in
        --container) USE_CONTAINER=1 ;;
        --arch=*) TARGET_ARCH="${arg#*=}" ;;
        --arch)
            arg_index=$((arg_index + 1))
            TARGET_ARCH="${!arg_index}"
            ;;
    esac
done
[ -n "$TARGET_ARCH" ] || TARGET_ARCH="$(uname -m)"
case "$TARGET_ARCH" in
    arm64|aarch64)
        TARGET_ARCH="aarch64"
        ;;
    x86_64|amd64)
        TARGET_ARCH="x86_64"
        QEMU_BIN="qemu-system-x86_64"
        DISK="$VM_DIR/ChurrOS.qcow2"
        VARS="$VM_DIR/OVMF_VARS.fd"
        ;;
    i386|i486|i586|i686)
        TARGET_ARCH="i686"
        QEMU_BIN="qemu-system-i386"
        DISK="$VM_DIR/ChurrOS-i686.qcow2"
        VARS="$VM_DIR/OVMF_VARS_ia32.fd"
        ;;
    *)
        echo "Error: unsupported architecture '$TARGET_ARCH' (use --arch x86_64, --arch arm64 or --arch i686)." >&2
        exit 1
        ;;
esac

# Si QEMU o el firmware OVMF no están en el host (o si se pasa --container),
# ejecutar QEMU en el contenedor Arch con aceleración gráfica y KVM.
if ! churros_in_container && { [ "$USE_CONTAINER" -eq 1 ] || ! command -v "$QEMU_BIN" >/dev/null 2>&1 || { [ "$TARGET_ARCH" != "i686" ] && ! churros_resolve_pflash "$TARGET_ARCH" "$VM_DIR" >/dev/null 2>&1; }; }; then
    ENGINE=""
    if command -v podman >/dev/null 2>&1; then
        ENGINE=podman
    elif command -v docker >/dev/null 2>&1; then
        ENGINE=docker
    fi

    if [ -n "$ENGINE" ]; then
        if [ "$USE_CONTAINER" -ne 1 ]; then
            echo "[qemu] $QEMU_BIN o firmware OVMF no disponible en el host."
            echo "[qemu] Ejecutando ChurrOS dentro del contenedor con aceleración gráfica y KVM..."
        fi

        if [ -n "${DISPLAY:-}" ] && command -v xhost >/dev/null 2>&1; then
            xhost +local: >/dev/null 2>&1 || true
        fi

        IMAGE="localhost/churros-builder"
        if [ "$TARGET_ARCH" = "aarch64" ]; then
            IMAGE="localhost/churros-builder-aarch64"
        fi
        if ! "$ENGINE" image exists "$IMAGE" 2>/dev/null && "$ENGINE" image exists localhost/churros-arch-shell 2>/dev/null; then
            IMAGE="localhost/churros-arch-shell"
        fi

        DEV_ARGS=()
        [ -e /dev/kvm ] && DEV_ARGS+=(--device /dev/kvm)
        [ -e /dev/dri ] && DEV_ARGS+=(--device /dev/dri)

        MOUNT_ARGS=(
            -v "$(cd "$(dirname "$0")/../.." && pwd):/churros"
            -w /churros
        )
        if [ -n "${DISPLAY:-}" ] && [ -d /tmp/.X11-unix ]; then
            MOUNT_ARGS+=(-v /tmp/.X11-unix:/tmp/.X11-unix:rw -e DISPLAY)
        fi
        if [ -n "${WAYLAND_DISPLAY:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -e "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; then
            MOUNT_ARGS+=(
                -v "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY:$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
                -e WAYLAND_DISPLAY
                -e XDG_RUNTIME_DIR
            )
        fi

        filtered_args=()
        for a in "$@"; do
            [ "$a" != "--container" ] && filtered_args+=("$a")
        done

        exec "$ENGINE" run --rm "${DEV_ARGS[@]}" "${MOUNT_ARGS[@]}" \
            -e CHURROS_IN_CONTAINER=1 \
            "$IMAGE" \
            bash ./scripts/cli/run.sh "${filtered_args[@]}"
    fi
fi

# CODE y VARS se eligen juntos para evitar mezclar firmwares incompatibles.
# i686 puede arrancar por BIOS si no hay firmware OVMF IA32.
mkdir -p "$VM_DIR"
pflash_out=""
if [ "$TARGET_ARCH" = "i686" ]; then
    pflash_out=$(churros_resolve_pflash "$TARGET_ARCH" "$VM_DIR" 2>/dev/null || true)
    if [ -z "$pflash_out" ]; then
        OVMF_CODE=""
        OVMF_VARS=""
    else
        OVMF_CODE=$(printf '%s\n' "$pflash_out" | sed -n '1p')
        OVMF_VARS=$(printf '%s\n' "$pflash_out" | sed -n '2p')
    fi
else
    if ! pflash_out=$(churros_resolve_pflash "$TARGET_ARCH" "$VM_DIR"); then
        echo "Error: OVMF firmware not found, do you have QEMU installed?"
        echo "Please configure the OVMF firmware paths manually otherwise."
        exit 1
    fi
    OVMF_CODE=$(printf '%s\n' "$pflash_out" | sed -n '1p')
    OVMF_VARS=$(printf '%s\n' "$pflash_out" | sed -n '2p')
fi

# Seleccionar siempre la ISO de la arquitectura pedida.
ISO=$(find out \( -name "*-${TARGET_ARCH}.iso" -o -name "*-${TARGET_ARCH}-*.iso" \) -print 2>/dev/null | sort | tail -n1)

FORCE_NOKVM=false
FORCE_FRESH=false
FORCE_CLEAN=false
for arg in "$@"; do
    case "$arg" in
        --nokvm) FORCE_NOKVM=true ;;
        --fresh) FORCE_FRESH=true ;;
        --clean) FORCE_CLEAN=true ;;
    esac
done

if [ -z "$OVMF_CODE" ] || [ -z "$OVMF_VARS" ]; then
    if [ "$TARGET_ARCH" = "i686" ]; then
        echo "OVMF IA32 firmware not found: arrancando por BIOS (SeaBIOS)."
    else
        echo "Error: OVMF firmware not found, do you have QEMU installed?"
        echo "Please configure the OVMF firmware paths manually otherwise."
        exit 1
    fi
else
    echo "OVMF firmware found:"
    echo "  OVMF_CODE: $OVMF_CODE"
    echo "  OVMF_VARS: $OVMF_VARS"
fi

# If no ISO was found, prompt the user to build ChurrOS
if [ -z "$ISO" ]; then
    echo "No ISO found."
    read -r -p "Do you want to build ChurrOS? [y/N] " answer

    case "$answer" in
        [yY]|[yY][eE][sS])
            echo "Building..."
            # --fresh y --nokvm son de run, no de build. En un host que no es
            # aarch64 la ISO ARM solo se puede construir en el contenedor.
            build_cmd=(./churros build --arch "$TARGET_ARCH")
            if [ "$TARGET_ARCH" = aarch64 ] && [ "$(uname -m)" != aarch64 ]; then
                build_cmd+=(--container)
            fi
            "${build_cmd[@]}"

            ISO=$(find out \( -name "*-${TARGET_ARCH}.iso" -o -name "*-${TARGET_ARCH}-*.iso" \) -print 2>/dev/null | sort | tail -n1)

            if [ -z "$ISO" ]; then
                echo "Error: Build completed, but no ISO was found."
                exit 1
            fi

            echo "ISO found: $ISO"
            ;;
        *)
            echo "Please specify the path to the ISO file."
            exit 1
            ;;
    esac
fi

mkdir -p "$VM_DIR"

if [ "$FORCE_CLEAN" = true ]; then
    echo "Full clean (--clean): removing disk and EFI vars..."
    rm -f "$DISK" "$VARS"
fi

if [ "$FORCE_FRESH" = true ] && [ -f "$VARS" ]; then
    echo "Resetting EFI vars (--fresh)..."
    rm -f "$VARS"
fi

if [ ! -f "$DISK" ]; then
    echo
    echo "Creating development virtual machine..."
    echo

    qemu-img create -f qcow2 "$DISK" 64G
fi

# ovmf.sh ya eligió un par coherente. En aarch64 QEMU exige además que las dos
# imágenes pflash midan lo mismo; en x86 CODE y VARS miden distinto (normal).
if [ -n "$OVMF_CODE" ] && [ -n "$OVMF_VARS" ]; then
    code_bytes=$(stat -L -c %s "$OVMF_CODE")
    template_vars_bytes=$(stat -L -c %s "$OVMF_VARS")
    if [ "$TARGET_ARCH" = aarch64 ] && [ "$code_bytes" != "$template_vars_bytes" ]; then
        echo "Error: el firmware pflash no coincide en tamaño." >&2
        echo "  CODE $OVMF_CODE ($code_bytes bytes)" >&2
        echo "  VARS $OVMF_VARS ($template_vars_bytes bytes)" >&2
        echo "Elige un par CODE/VARS de la misma generación (p. ej. AAVMF_CODE + AAVMF_VARS)." >&2
        exit 1
    fi

    # Si las variables EFI existentes pertenecen a otro firmware, se reinician.
    if [ -f "$VARS" ] && [ "$(stat -L -c %s "$VARS")" != "$template_vars_bytes" ]; then
        echo "EFI vars size does not match firmware template ($template_vars_bytes bytes); resetting $VARS"
        rm -f "$VARS"
    fi
    if [ ! -f "$VARS" ]; then
        cp "$OVMF_VARS" "$VARS"
    fi
fi

echo
echo "Launching ChurrOS Development VM..."
echo

KVM_ARGS=()
GPU_ARGS=()
CPU_ARGS=()
MACHINE_ARGS=()
AUDIO_ARGS=()

if [ "$TARGET_ARCH" = "aarch64" ]; then
    # virt no tiene IDE: -cdrom no engancha el disco. virtio-scsi + scsi-cd,
    # disco virtio-blk y teclado USB (tampoco hay PS/2). La serie es PL011
    # (console=ttyAMA0 en el menú GRUB).
    if [ "$FORCE_NOKVM" = false ] && [ "$(uname -m)" = aarch64 ] && [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
        echo "  ARM64 QEMU: KVM"
        KVM_ARGS=(-cpu host)
        CPU_ARGS=(-smp 4)
        MACHINE_ARGS=(-machine "virt,accel=kvm")
    else
        echo "  ARM64 QEMU: TCG software emulation"
        KVM_ARGS=(-cpu cortex-a72)
        CPU_ARGS=(-smp 4)
        MACHINE_ARGS=(-machine virt)
    fi
    GPU_ARGS=(-device virtio-gpu-gl-pci,xres=1920,yres=1080 -display "gtk,gl=on,show-cursor=on")
elif [ "$TARGET_ARCH" = "i686" ]; then
    if [ "$FORCE_NOKVM" = false ] && [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
        echo "  KVM acceleration: enabled (i686)"
        KVM_ARGS=(-cpu host)
        CPU_ARGS=(-smp 4)
        MACHINE_ARGS=(-machine "q35,accel=kvm")
    else
        echo "  KVM acceleration: not available (using software emulation)"
        KVM_ARGS=(-cpu qemu32)
        CPU_ARGS=(-smp 2)
        MACHINE_ARGS=(-machine q35)
    fi
elif [ "$FORCE_NOKVM" = false ] && [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    echo "  KVM acceleration: enabled"
    KVM_ARGS=(-cpu host)
    CPU_ARGS=(-smp 4)
    MACHINE_ARGS=(-machine "q35,accel=kvm")
else
    echo "  KVM acceleration: not available (using software emulation)"
    CPU_ARGS=(-smp 2)
    MACHINE_ARGS=(-machine q35)
fi

# niri requires hardware-accelerated 3D (OpenGL via virgl).
# Always attempt virtio-gpu-gl with GL; fall back to virtio-gpu (no GL) only if
# the host lacks /dev/dri entirely. niri 26.04 skips software EGL (llvmpipe), so
# without virgl it starts with no output; tests/vm uses Xvfb + Mesa instead.
if [ -e /dev/dri ]; then
    if [ "$TARGET_ARCH" = "aarch64" ]; then
        echo "  GPU: virtio-gpu-gl-pci + virgl (3D)"
    else
        GPU_ARGS=(-device virtio-vga-gl,xres=1920,yres=1080 -display "gtk,gl=on,show-cursor=on")
        echo "  GPU: virtio-vga-gl + virgl (3D)"
    fi
else
    if [ "$TARGET_ARCH" != "aarch64" ]; then
        GPU_ARGS=(-device virtio-gpu,xres=1920,yres=1080 -display "gtk,gl=off,show-cursor=on")
    fi
    echo "  GPU: virtio-gpu (no 3D — niri will start without any output: black screen)"
fi

if [ "$TARGET_ARCH" != "aarch64" ]; then
    AUDIO_ARGS=(-device intel-hda -device hda-duplex)
fi

QEMU_CMD=(
    "$QEMU_BIN"
    "${MACHINE_ARGS[@]}"
    "${KVM_ARGS[@]}"
    "${CPU_ARGS[@]}"
    -m 4096
    "${GPU_ARGS[@]}"
    -device qemu-xhci
    -device usb-tablet
)
if [ "$TARGET_ARCH" = aarch64 ]; then
    QEMU_CMD+=(-device usb-kbd)
fi
QEMU_CMD+=(
    "${AUDIO_ARGS[@]}"
    -device virtio-serial-pci
    -chardev "qemu-vdagent,id=vdagent,name=vdagent,clipboard=on"
    -device "virtserialport,chardev=vdagent,name=com.redhat.spice.0"
)
if [ -n "$OVMF_CODE" ] && [ -n "$OVMF_VARS" ]; then
    QEMU_CMD+=(
        -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE"
        -drive "if=pflash,format=raw,file=$VARS"
    )
fi
if [ "$TARGET_ARCH" = aarch64 ]; then
    QEMU_CMD+=(
        -device "virtio-scsi-pci,id=scsi0"
        -device "scsi-cd,bus=scsi0.0,drive=cdrom0,bootindex=0"
        -drive "id=cdrom0,if=none,format=raw,readonly=on,file=$ISO"
        -device "virtio-blk-pci,drive=disk0,bootindex=1"
        -drive "id=disk0,if=none,format=qcow2,file=$DISK,cache=writeback,discard=unmap"
    )
else
    QEMU_CMD+=(
        -drive "file=$DISK,format=qcow2,if=virtio,cache=writeback,discard=unmap"
        -cdrom "$ISO"
        -boot order=c
    )
fi
QEMU_CMD+=(-serial file:vm_serial.log)

"${QEMU_CMD[@]}"
