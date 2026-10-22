# shellcheck shell=bash
#
# scripts/lib/cluster.sh — Biblioteca de gestión del cluster de compilación ChurrOS
#

churros_cluster_root_dir() {
    cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

churros_cluster_config_path() {
    printf '%s/cluster.conf\n' "$(churros_cluster_root_dir)"
}

churros_cluster_is_configured() {
    local conf
    conf="$(churros_cluster_config_path)"
    [ -f "$conf" ] || return 1
    grep -qE '^[[:space:]]*NODES=\(' "$conf" 2>/dev/null
}

churros_cluster_load_config() {
    local conf
    conf="$(churros_cluster_config_path)"
    if [ ! -f "$conf" ]; then
        echo "Error: No se encontró cluster.conf. Ejecuta './churros cluster init' primero." >&2
        return 1
    fi

    # Valores por defecto antes de cargar configuración
    NODES=()
    CLUSTER_RUNNER="podman"
    DISTCCD_PORT=3632
    ALLOWED_NETS="0.0.0.0/0"
    INCLUDE_LOCALHOST=true
    SSH_OPTS="-o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

    # shellcheck source=/dev/null
    source "$conf"

    if [ "${#NODES[@]}" -eq 0 ]; then
        echo "Error: cluster.conf no define ningún nodo en el array NODES." >&2
        return 1
    fi
}

# Parsea una entrada "target[,threads]" -> imprime "target threads host"
churros_cluster_parse_node() {
    local entry="$1"
    local target threads host
    target="${entry%%,*}"
    if [[ "$entry" == *","* ]]; then
        threads="${entry##*,}"
    else
        threads=24
    fi

    if [[ "$target" == *"@"* ]]; then
        host="${target##*@}"
    else
        host="$target"
    fi

    printf '%s %s %s\n' "$target" "$threads" "$host"
}

# Verifica si el puerto de distccd responde en el host
churros_cluster_test_port() {
    local host="$1"
    local port="${2:-3632}"
    timeout 2 bash -c "cat < /dev/null > /dev/tcp/$host/$port" 2>/dev/null
}

# Prueba de conectividad e inspección remota
churros_cluster_probe_node() {
    local target="$1"
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "$target" bash -s <<'EOF'
echo "OS: $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"' || uname -s)"
echo "CPU: $(lscpu 2>/dev/null | grep "Model name" | head -n1 | sed -e 's/Model name:[[:space:]]*//' || echo "Unknown")"
echo "CORES: $(nproc 2>/dev/null || echo 1)"
echo "RAM: $(free -h 2>/dev/null | awk '/^Mem:/ {print $2}' || echo "Unknown")"
echo "RUNNERS: $(which podman docker 2>/dev/null | tr '\n' ' ' || echo "none")"
echo "DISTCCD: $(which distccd 2>/dev/null || echo "not-installed")"
EOF
}

# Arranca distccd en un nodo remoto
churros_cluster_start_node() {
    local target="$1"
    local threads="$2"
    local runner="$CLUSTER_RUNNER"
    local port="$DISTCCD_PORT"
    local nets="$ALLOWED_NETS"

    # shellcheck disable=SC2086
    ssh $SSH_OPTS "$target" "bash -s" <<EOF
set -e
if [ "$runner" = "podman" ] || [ "$runner" = "docker" ]; then
    if command -v "$runner" >/dev/null 2>&1; then
        if $runner ps -q --filter "name=churros-distccd" | grep -q .; then
            echo "running"
            exit 0
        fi
        $runner rm -f churros-distccd 2>/dev/null || true
        # Iniciar contenedor Arch con distccd
        $runner run -d --rm --name churros-distccd \
            --net=host \
            docker.io/library/archlinux:latest \
            bash -c "pacman -Sy --noconfirm --needed distcc clang llvm >/dev/null 2>&1 && exec distccd --no-detach --daemon --port $port --log-stderr --allow $nets --jobs $threads" >/dev/null
        echo "started"
        exit 0
    else
        echo "runner-not-found"
        exit 1
    fi
elif [ "$runner" = "native" ]; then
    if command -v distccd >/dev/null 2>&1; then
        if pgrep -f "distccd.*$port" >/dev/null 2>&1; then
            echo "running"
            exit 0
        fi
        distccd --daemon --port "$port" --allow "$nets" --jobs "$threads" --log-stderr
        echo "started"
        exit 0
    else
        echo "distccd-not-found"
        exit 1
    fi
fi
EOF
}

# Detiene el worker distccd en un nodo remoto
churros_cluster_stop_node() {
    local target="$1"
    local runner="$CLUSTER_RUNNER"

    # shellcheck disable=SC2086
    ssh $SSH_OPTS "$target" "bash -s" <<EOF
if [ "$runner" = "podman" ] || [ "$runner" = "docker" ]; then
    $runner stop churros-distccd 2>/dev/null || true
fi
pkill -u \$USER distccd 2>/dev/null || true
echo "stopped"
EOF
}

# Genera la cadena DISTCC_HOSTS con todos los nodos configurados
churros_cluster_distcc_hosts() {
    local hosts=()
    local node target threads host
    for node in "${NODES[@]}"; do
        [ -n "$node" ] || continue
        read -r target threads host <<<"$(churros_cluster_parse_node "$node")"
        hosts+=("${host}:${DISTCCD_PORT}/${threads}")
    done

    if [ "$INCLUDE_LOCALHOST" = true ]; then
        local local_threads
        local_threads="$(nproc)"
        hosts+=("localhost/${local_threads}")
    fi

    printf '%s ' "${hosts[@]}"
}

# Calcula el total de hilos (remotos + locales)
churros_cluster_total_threads() {
    local total=0
    local node target threads host
    for node in "${NODES[@]}"; do
        [ -n "$node" ] || continue
        read -r target threads host <<<"$(churros_cluster_parse_node "$node")"
        total=$((total + threads))
    done

    if [ "$INCLUDE_LOCALHOST" = true ]; then
        total=$((total + $(nproc)))
    fi

    printf '%s\n' "$total"
}

# Detecta la subred local de la interfaz activa
churros_cluster_detect_subnet() {
    local cidr
    cidr=$(ip -o -4 addr show scope global 2>/dev/null | grep -vE 'docker|veth|br-|cni|virbr' | head -n1 | awk '{print $4}' || true)
    if [ -n "$cidr" ]; then
        printf '%s\n' "$cidr"
    else
        echo "192.168.1.0/24"
    fi
}

# Escanea la subred en busca de máquinas con SSH (puerto 22) abierto
churros_cluster_scan_subnet() {
    local subnet="$1"
    local my_ip
    my_ip="$(ip -o -4 addr show scope global 2>/dev/null | grep -vE 'docker|veth|br-|cni|virbr' | head -n1 | awk '{print $4}' | cut -d/ -f1 || echo "127.0.0.1")"

    # Si nmap está instalado, usarlo para máxima velocidad
    if command -v nmap >/dev/null 2>&1; then
        nmap -p 22 --open -sT -n -oG - "$subnet" 2>/dev/null | awk '/22\/open/ {print $2}' | grep -v "^$my_ip$" || true
        return 0
    fi

    # Escaneo ultrarrápido en paralelo nativo de Bash sin herramientas externas
    local base="${subnet%.*.*}"
    # Si la subred es tipo x.x.x.y/24
    if [[ "$subnet" =~ ^([0-9]+\.[0-9]+\.[0-9]+)\. ]]; then
        base="${BASH_REMATCH[1]}."
    else
        base="${subnet%.*}."
    fi

    local tmp_dir
    tmp_dir="$(mktemp -d /tmp/churros-scan.XXXXXX)"
    for i in $(seq 1 254); do
        (
            local target_ip="${base}${i}"
            if [ "$target_ip" != "$my_ip" ]; then
                if timeout 1 bash -c "cat < /dev/null > /dev/tcp/$target_ip/22" 2>/dev/null; then
                    echo "$target_ip" > "$tmp_dir/$i"
                fi
            fi
        ) &
    done
    wait

    if [ -d "$tmp_dir" ]; then
        cat "$tmp_dir"/* 2>/dev/null | sort -V || true
        rm -rf "$tmp_dir"
    fi
}

# Guarda los nodos descubiertos en cluster.conf
churros_cluster_save_nodes() {
    local conf
    conf="$(churros_cluster_config_path)"
    local runner="${CLUSTER_RUNNER:-podman}"
    local port="${DISTCCD_PORT:-3632}"
    local nets="${ALLOWED_NETS:-0.0.0.0/0}"
    local localhost="${INCLUDE_LOCALHOST:-true}"

    {
        echo "# =============================================================================="
        echo "# ChurrOS Distributed Compilation Cluster Configuration"
        echo "# Generado automáticamente por './churros cluster scan'"
        echo "# =============================================================================="
        echo
        echo "NODES=("
        for n in "$@"; do
            echo "    \"$n\""
        done
        echo ")"
        echo
        echo "CLUSTER_RUNNER=\"$runner\""
        echo "DISTCCD_PORT=$port"
        echo "ALLOWED_NETS=\"$nets\""
        echo "INCLUDE_LOCALHOST=$localhost"
        echo "SSH_OPTS=\"-o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new\""
    } > "$conf"
}

