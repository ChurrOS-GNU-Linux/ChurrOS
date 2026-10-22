#!/usr/bin/env bash
#
# scripts/cli/cluster.sh — CLI de control del cluster distribuido ChurrOS
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# shellcheck source=scripts/lib/cluster.sh
source "$SCRIPT_DIR/../lib/cluster.sh"

show_cluster_help() {
    echo "================================================================="
    echo "       ChurrOS Distributed Compilation Cluster Manager"
    echo "================================================================="
    echo
    echo "Uso:"
    echo "  ./churros cluster <subcomando> [opciones]"
    echo
    echo "Subcomandos disponibles:"
    echo "  scan         Escanea la red del switch y detecta automáticamente las IPs de los nodos"
    echo "  auth         Copia llaves SSH para acceso sin contraseña a todos los nodos"
    echo "  init         Crea el archivo de configuración cluster.conf desde la plantilla"
    echo "  probe        Prueba conectividad SSH e inspecciona hardware/software de cada nodo"
    echo "  start        Inicia los workers de distccd en todos los nodos del cluster"
    echo "  status       Verifica el estado de los workers remotos y muestra hilos totales"
    echo "  stop         Detiene los workers de distccd en los nodos remotos"
    echo "  build        Compila el kernel ChurrOSvyper usando el cluster distribuido"
    echo "  monitor      Muestra el monitor de compilación en tiempo real (distccmon)"
    echo
    echo "Ejemplos:"
    echo "  ./churros cluster scan"
    echo "  ./churros cluster start"
    echo "  ./churros cluster build"
    echo "  ./churros cluster stop"
    echo
}

cmd_scan() {
    local subnet=""
    local user="${USER}"
    local auto_save=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --subnet|-s)
                subnet="$2"
                shift 2
                ;;
            --user|-u)
                user="$2"
                shift 2
                ;;
            --yes|-y)
                auto_save=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done

    [ -n "$subnet" ] || subnet="$(churros_cluster_detect_subnet)"

    echo "================================================================="
    echo "  Escaneando Red Local del Switch en Busca de Nodos"
    echo "================================================================="
    echo "Subred:      $subnet"
    echo "Usuario SSH: $user"
    echo "Escaneando máquinas conectadas al switch con SSH (puerto 22)..."
    echo

    local ips=()
    while IFS= read -r ip; do
        [ -n "$ip" ] || continue
        ips+=("$ip")
    done < <(churros_cluster_scan_subnet "$subnet")

    if [ "${#ips[@]}" -eq 0 ]; then
        echo "No se encontraron máquinas con el puerto 22 abierto en la subred $subnet."
        echo "Asegúrate de que las PCs estén encendidas y conectadas al switch."
        return 1
    fi

    echo "Se detectaron ${#ips[@]} máquinas activas. Analizando núcleos..."
    echo

    local discovered_nodes=()
    local total_cores=0

    for ip in "${ips[@]}"; do
        printf "▸ Analizando %-16s ... " "$ip"
        local nproc_out
        if nproc_out=$(ssh -o ConnectTimeout=2 -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$user@$ip" "nproc 2>/dev/null" 2>/dev/null); then
            local cores="${nproc_out:-24}"
            echo "✓ CONECTADO ($cores núcleos detectados)"
            discovered_nodes+=("${user}@${ip},${cores}")
            total_cores=$((total_cores + cores))
        else
            echo "○ DETECTADO (puerto 22 activo, asignando 24 hilos)"
            discovered_nodes+=("${user}@${ip},24")
            total_cores=$((total_cores + 24))
        fi
    done

    echo
    echo "-----------------------------------------------------------------"
    echo "Resumen del escaneo:"
    echo "  Total de nodos encontrados: ${#discovered_nodes[@]}"
    echo "  Capacidad combinada:        $total_cores hilos remotos"
    echo "-----------------------------------------------------------------"
    echo

    local save=false
    if [ "$auto_save" = true ]; then
        save=true
    else
        read -r -p "¿Deseas guardar estos ${#discovered_nodes[@]} nodos en cluster.conf? [S/n]: " resp || resp="s"
        case "$resp" in
            ""|[yYsS]*) save=true ;;
        esac
    fi

    if [ "$save" = true ]; then
        churros_cluster_save_nodes "${discovered_nodes[@]}"
        echo "✓ cluster.conf generado automáticamente con éxito."
        echo "Ahora puedes ejecutar:"
        echo "  ./churros cluster probe"
        echo "  ./churros cluster start"
        echo "  ./churros cluster build"
    else
        echo "Operación cancelada. No se modificó cluster.conf."
    fi
}

cmd_init() {
    local conf
    conf="$(churros_cluster_config_path)"
    if [ -f "$conf" ]; then
        echo "El archivo cluster.conf ya existe en: $conf"
        echo "Edítalo para ajustar la lista de nodos."
        return 0
    fi

    local tmpl="$PROJECT_DIR/cluster.conf.example"
    if [ -f "$tmpl" ]; then
        cp "$tmpl" "$conf"
        echo "✓ Archivo creado: $conf"
        echo "Configura tus nodos (IPs, usuarios y núcleos) abriendo 'cluster.conf'."
    else
        echo "Error: no se encontró la plantilla $tmpl" >&2
        return 1
    fi
}

cmd_auth() {
    churros_cluster_load_config
    echo "================================================================="
    echo "  Configuración de Llaves SSH Sin Contraseña (${#NODES[@]} nodos)"
    echo "================================================================="
    echo

    local key_file="$HOME/.ssh/id_ed25519"
    if [ ! -f "$key_file.pub" ] && [ ! -f "$HOME/.ssh/id_rsa.pub" ]; then
        echo "Generando par de llaves SSH local..."
        mkdir -p "$HOME/.ssh"
        chmod 700 "$HOME/.ssh"
        ssh-keygen -t ed25519 -N "" -f "$key_file" >/dev/null
        echo "✓ Llave generada en $key_file.pub"
    fi

    local has_sshpass=false
    if command -v sshpass >/dev/null 2>&1; then
        has_sshpass=true
    fi

    local password=""
    if [ "$has_sshpass" = true ]; then
        echo "Se detectó sshpass: puedes ingresar tu contraseña una sola vez y se"
        echo "copiará automáticamente a todas las máquinas."
        read -r -s -p "Introduce la contraseña de SSH para los nodos: " password
        echo
        echo
    else
        echo "Copiaremos tu llave a cada nodo. Se te pedirá la contraseña una sola vez por máquina."
        echo
    fi

    local auth_success=0
    for entry in "${NODES[@]}"; do
        [ -n "$entry" ] || continue
        local target threads host
        read -r target threads host <<<"$(churros_cluster_parse_node "$entry")"

        printf "▸ Autorizando en %-28s ... " "$target"
        local copy_ok=false
        if [ "$has_sshpass" = true ] && [ -n "$password" ]; then
            if sshpass -p "$password" ssh-copy-id -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 "$target" >/dev/null 2>&1; then
                copy_ok=true
            fi
        else
            if ssh-copy-id -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 "$target" >/dev/null 2>&1; then
                copy_ok=true
            fi
        fi

        if [ "$copy_ok" = true ]; then
            echo "✓ AUTORIZADO"
            auth_success=$((auth_success + 1))
        else
            echo "✗ FALLÓ"
        fi
    done

    echo
    echo "-----------------------------------------------------------------"
    echo "Nodos autorizados sin contraseña: $auth_success/${#NODES[@]}"
    echo "-----------------------------------------------------------------"
}

cmd_probe() {
    churros_cluster_load_config
    echo "================================================================="
    echo "  Sondeando Nodos del Cluster (${#NODES[@]} configurados)"
    echo "================================================================="
    echo

    local success_count=0
    local total_threads=0

    for entry in "${NODES[@]}"; do
        [ -n "$entry" ] || continue
        local target threads host
        read -r target threads host <<<"$(churros_cluster_parse_node "$entry")"

        printf "▸ Conectando a %-28s ... " "$target"
        local probe_out
        if probe_out="$(churros_cluster_probe_node "$target" 2>&1)"; then
            echo "✓ CONECTADO"
            local cpu os cores ram runners distccd
            os="$(echo "$probe_out" | grep "^OS:" | cut -d' ' -f2-)"
            cpu="$(echo "$probe_out" | grep "^CPU:" | cut -d' ' -f2-)"
            cores="$(echo "$probe_out" | grep "^CORES:" | cut -d' ' -f2-)"
            ram="$(echo "$probe_out" | grep "^RAM:" | cut -d' ' -f2-)"
            runners="$(echo "$probe_out" | grep "^RUNNERS:" | cut -d' ' -f2-)"
            distccd="$(echo "$probe_out" | grep "^DISTCCD:" | cut -d' ' -f2-)"

            echo "    OS:       $os"
            echo "    CPU:      $cpu"
            echo "    Núcleos:  $cores hilos (configurados: $threads)"
            echo "    RAM:      $ram"
            echo "    Motores:  ${runners:-ninguno}"
            echo "    Distccd:  $distccd"
            echo
            success_count=$((success_count + 1))
            total_threads=$((total_threads + threads))
        else
            echo "✗ FALLÓ"
            echo "    Error: $probe_out"
            echo
        fi
    done

    echo "-----------------------------------------------------------------"
    echo "Resumen: $success_count/${#NODES[@]} nodos alcanzables. Capacidad estimada: $total_threads hilos."
    echo "-----------------------------------------------------------------"
}

cmd_start() {
    churros_cluster_load_config
    echo "================================================================="
    echo "  Iniciando Workers Distccd en el Cluster ($CLUSTER_RUNNER)"
    echo "================================================================="
    echo

    local started=0
    for entry in "${NODES[@]}"; do
        [ -n "$entry" ] || continue
        local target threads host
        read -r target threads host <<<"$(churros_cluster_parse_node "$entry")"

        printf "▸ Iniciando worker en %-28s (%s hilos) ... " "$target" "$threads"
        local res
        if res="$(churros_cluster_start_node "$target" "$threads" 2>&1)"; then
            if [[ "$res" == *"running"* ]]; then
                echo "✓ YA ESTÁ ACTIVO"
            elif [[ "$res" == *"started"* ]]; then
                echo "✓ INICIADO"
            else
                echo "✓ $res"
            fi
            started=$((started + 1))
        else
            echo "✗ ERROR"
            echo "    $res"
        fi
    done

    echo
    echo "Workers desplegados: $started/${#NODES[@]}."
    echo "Ejecuta './churros cluster status' para verificar puertos."
}

cmd_status() {
    churros_cluster_load_config
    echo "================================================================="
    echo "  Estado del Cluster ChurrOS (Puerto $DISTCCD_PORT)"
    echo "================================================================="
    echo

    local active_nodes=0
    local active_threads=0

    for entry in "${NODES[@]}"; do
        [ -n "$entry" ] || continue
        local target threads host
        read -r target threads host <<<"$(churros_cluster_parse_node "$entry")"

        printf "▸ Nodo %-26s [%s:%s] ... " "$target" "$host" "$DISTCCD_PORT"
        if churros_cluster_test_port "$host" "$DISTCCD_PORT"; then
            echo "● ONLINE ($threads hilos)"
            active_nodes=$((active_nodes + 1))
            active_threads=$((active_threads + threads))
        else
            echo "○ OFFLINE / BLOQUEADO"
        fi
    done

    local local_threads
    local_threads="$(nproc)"
    if [ "$INCLUDE_LOCALHOST" = true ]; then
        echo "▸ Host local (localhost)                   ... ● ONLINE ($local_threads hilos)"
        active_threads=$((active_threads + local_threads))
    fi

    echo "-----------------------------------------------------------------"
    echo "Nodos activos: $active_nodes/${#NODES[@]}"
    echo "Potencia total de compilación disponible: $active_threads hilos (-j$active_threads)"
    echo "Cadena DISTCC_HOSTS:"
    echo "  $(churros_cluster_distcc_hosts)"
    echo "-----------------------------------------------------------------"
}

cmd_stop() {
    churros_cluster_load_config
    echo "================================================================="
    echo "  Deteniendo Workers Distccd en el Cluster"
    echo "================================================================="
    echo

    for entry in "${NODES[@]}"; do
        [ -n "$entry" ] || continue
        local target threads host
        read -r target threads host <<<"$(churros_cluster_parse_node "$entry")"

        printf "▸ Deteniendo worker en %-28s ... " "$target"
        if churros_cluster_stop_node "$target" >/dev/null 2>&1; then
            echo "✓ DETENIDO"
        else
            echo "✗ ERROR AL DETENER"
        fi
    done
    echo "Completado."
}

cmd_build() {
    # shellcheck source=scripts/lib/host.sh
    source "$PROJECT_DIR/scripts/lib/host.sh"
    if ! churros_host_is_arch && ! churros_in_container; then
        echo "Host detectado: $(churros_host_name) (no Arch Linux)."
        echo "Ejecutando la compilación del cluster dentro del contenedor Arch del proyecto..."
        exec "$PROJECT_DIR/churros" build --container --cluster "$@"
    else
        echo "Lanzando compilación del kernel con aceleración de cluster..."
        bash "$PROJECT_DIR/scripts/build-kernel-vyper.sh" --cluster "$@"
    fi
}

cmd_monitor() {
    churros_cluster_load_config
    export DISTCC_HOSTS
    DISTCC_HOSTS="$(churros_cluster_distcc_hosts)"
    if command -v distccmon-text >/dev/null 2>&1; then
        echo "Iniciando monitor distcc (Ctrl+C para salir)..."
        exec distccmon-text 1
    elif command -v podman >/dev/null 2>&1; then
        echo "distccmon-text no está en el host. Ejecutando monitor vía Podman..."
        exec podman run --rm -it --net=host -e DISTCC_HOSTS="$DISTCC_HOSTS" docker.io/library/archlinux:latest bash -c "pacman -Sy --noconfirm distcc >/dev/null 2>&1 && distccmon-text 1"
    else
        echo "distccmon-text no está instalado en el host."
        exit 1
    fi
}

subcommand="${1:-help}"
shift || true

case "$subcommand" in
    scan)      cmd_scan "$@" ;;
    auth)      cmd_auth "$@" ;;
    init)      cmd_init "$@" ;;
    probe)     cmd_probe "$@" ;;
    start)     cmd_start "$@" ;;
    status)    cmd_status "$@" ;;
    stop)      cmd_stop "$@" ;;
    build)     cmd_build "$@" ;;
    monitor)   cmd_monitor "$@" ;;
    help|-h|--help) show_cluster_help ;;
    *)
        echo "Error: subcomando de cluster desconocido '$subcommand'" >&2
        show_cluster_help
        exit 1
        ;;
esac
