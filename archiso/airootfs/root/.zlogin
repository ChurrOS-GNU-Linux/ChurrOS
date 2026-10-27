# fix for screen readers
if grep -Fqa 'accessibility=' /proc/cmdline &> /dev/null; then
    setopt SINGLE_LINE_ZLE
fi

# Sin +x, zsh imprime "permission denied" y no llega al script=.
if [[ -x ~/.automated_script.sh ]]; then
    ~/.automated_script.sh
fi

# greetd sustituye a getty@tty1 y esta shell muere con el exec. Una consola
# serie o un login de root en otro tty tiene que seguir usable. Si greetd
# ya está activo, tampoco reemplazar la shell.
if [[ "$(tty 2>/dev/null)" == "/dev/tty1" ]] && ! systemctl is-active --quiet greetd.service; then
    exec systemctl start greetd.service 2>/dev/null
fi
