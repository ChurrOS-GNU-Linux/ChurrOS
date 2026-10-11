#!/usr/bin/env bash

set -e

# shellcheck source=scripts/lib/ovmf.sh
source "$(cd "$(dirname "$0")/.." && pwd)/lib/ovmf.sh"

VM_DIR="vm"
# Sin --arch se usa la arquitectura del equipo, igual que ./churros build.
TARGET_ARCH=""
QEMU_BIN="qemu-system-aarch64"
DISK="$VM_DIR/ChurrOS-arm64.qcow2"
VARS="$VM_DIR/OVMF_VARS_arm64.fd"

for ((arg_index = 1; arg_index <= $#; arg_index++)); do
    arg="${!arg_index}"
    case "$arg" in
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
    *)
        echo "Error: unsupported architecture '$TARGET_ARCH' (use --arch arm64 or --arch x86_64)." >&2
        exit 1
        ;;
esac

# CODE y VARS se eligen juntos. El primer par en el que ambos existen y
# miden igual gana (AAVMF_CODE+AAVMF_VARS, QEMU_CODE+QEMU_VARS, OVMF *.4m).
# Un QEMU_EFI.fd crudo sin pareja se rellena a 64 MiB.
mkdir -p "$VM_DIR"
if ! pflash_out=$(churros_resolve_pflash "$TARGET_ARCH" "$VM_DIR"); then
    echo "Error: OVMF firmware not found, do you have QEMU installed?"
    echo "Please configure the OVMF firmware paths manually otherwise."
    exit 1
fi
OVMF_CODE=$(printf '%s\n' "$pflash_out" | sed -n '1p')
OVMF_VARS=$(printf '%s\n' "$pflash_out" | sed -n '2p')

# El nombre que pone mkarchiso lleva la arquitectura (…-aarch64.iso).
# Si no, un out/ con una ISO x86_64 se arrancaría en QEMU ARM.
if [ "$TARGET_ARCH" = aarch64 ]; then
    ISO=$(find out -name '*aarch64*.iso' 2>/dev/null | head -n1)
else
    ISO=$(find out -name '*x86_64*.iso' 2>/dev/null | head -n1)
fi

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
    echo "Error: OVMF firmware not found, do you have QEMU installed?"
    echo "Please configure the OVMF firmware paths manually otherwise."
    exit 1
fi
echo "OVMF firmware found:"
echo "  OVMF_CODE: $OVMF_CODE"
echo "  OVMF_VARS: $OVMF_VARS"

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

            if [ "$TARGET_ARCH" = aarch64 ]; then
                ISO=$(find out -name '*aarch64*.iso' -print -quit)
            else
                ISO=$(find out -name '*x86_64*.iso' -print -quit)
            fi

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
code_bytes=$(stat -L -c %s "$OVMF_CODE")
template_vars_bytes=$(stat -L -c %s "$OVMF_VARS")
if [ "$TARGET_ARCH" = aarch64 ] && [ "$code_bytes" != "$template_vars_bytes" ]; then
    echo "Error: el firmware pflash no coincide en tamaño." >&2
    echo "  CODE $OVMF_CODE ($code_bytes bytes)" >&2
    echo "  VARS $OVMF_VARS ($template_vars_bytes bytes)" >&2
    echo "Elige un par CODE/VARS de la misma generación (p. ej. AAVMF_CODE + AAVMF_VARS)." >&2
    exit 1
fi

# If the OVMF vars file doesn't exist, copy the default one to the VM directory.
# Una VARS vieja de otro firmware (tamaño distinto a la plantilla) se descarta.
if [ -f "$VARS" ] && [ "$(stat -L -c %s "$VARS")" != "$template_vars_bytes" ]; then
    echo "EFI vars size does not match firmware template ($template_vars_bytes bytes); resetting $VARS"
    rm -f "$VARS"
fi
if [ ! -f "$VARS" ]; then
    cp "$OVMF_VARS" "$VARS"
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
    GPU_ARGS=(-device virtio-gpu-gl-pci -display "gtk,gl=on,show-cursor=on")
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
# the host lacks /dev/dri entirely — in that case niri will try llvmpipe.
if [ -e /dev/dri ]; then
    if [ "$TARGET_ARCH" = "x86_64" ]; then
        GPU_ARGS=(-device virtio-vga-gl -display "gtk,gl=on,show-cursor=on")
        echo "  GPU: virtio-vga-gl + virgl (3D)"
    else
        echo "  GPU: virtio-gpu-gl-pci + virgl (3D)"
    fi
else
    if [ "$TARGET_ARCH" = "x86_64" ]; then
        GPU_ARGS=(-device virtio-gpu -display "gtk,gl=off,show-cursor=on")
    fi
    echo "  GPU: virtio-gpu (no 3D — niri may fall back to software rendering)"
fi

if [ "$TARGET_ARCH" = "x86_64" ]; then
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
    -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE"
    -drive "if=pflash,format=raw,file=$VARS"
)
if [ "$TARGET_ARCH" = aarch64 ]; then
    QEMU_CMD+=(
        -device "virtio-scsi-pci,id=scsi0"
        -device "scsi-cd,bus=scsi0.0,drive=cdrom0,bootindex=0"
        -drive "id=cdrom0,if=none,format=raw,readonly=on,file=$ISO"
        -device "virtio-blk-pci,drive=disk0,bootindex=1"
        -drive "id=disk0,if=none,format=qcow2,file=$DISK"
    )
else
    QEMU_CMD+=(
        -drive "file=$DISK,format=qcow2,if=virtio"
        -cdrom "$ISO"
        -boot order=c
    )
fi
QEMU_CMD+=(-serial file:vm_serial.log)

"${QEMU_CMD[@]}"
