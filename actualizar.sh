#!/usr/bin/env bash
# Actualiza el bot en la Raspberry con un solo comando:
#
#     bash actualizar.sh            # actualiza si hay algo nuevo en GitHub
#     bash actualizar.sh --forzar   # reinicia y comprueba aunque no haya cambios
#
# Qué hace: para el servicio, guarda una copia del estado, trae la última versión de GitHub, instala las
# dependencias si cambiaron, comprueba que el código no está roto, arranca el servicio y verifica que sigue vivo.
# Si algo falla vuelve solo a la versión anterior.
#
# Variables opcionales: SERVICE (nombre del servicio, por defecto "wallapop"), ESPERA (segundos que se espera
# antes de dar el arranque por bueno, por defecto 15).

# Todo va dentro de una función para que bash lea el script entero ANTES de ejecutarlo: así 'git pull' puede
# sustituir este mismo archivo por una versión nueva sin romper la ejecución en curso.
main() {
    set -u
    cd "$(dirname "$(readlink -f "$0")")" || { echo "❌ No puedo entrar en la carpeta del bot."; return 1; }

    local SERVICE="${SERVICE:-wallapop}" ESPERA="${ESPERA:-15}" FORZAR=0
    local PY="./venv/bin/python" PIP="./venv/bin/pip" BACKUPS="$HOME/wallapop-backups"
    local SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

    case "${1:-}" in
        --forzar) FORZAR=1 ;;
        -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; return 0 ;;
        "") ;;
        *) echo "Opción desconocida: $1 (usa --forzar o --help)"; return 1 ;;
    esac

    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "❌ Esto no es un repositorio git."; return 1; }
    [ -x "$PY" ] || { echo "❌ No encuentro $PY (¿la carpeta venv?)."; return 1; }
    local RAMA; RAMA="$(git rev-parse --abbrev-ref HEAD)"
    git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1 || { echo "❌ La rama '$RAMA' no está enlazada con GitHub."; return 1; }

    echo "🔎 Buscando novedades en GitHub..."
    git fetch -q || { echo "❌ No consigo conectar con GitHub (¿sin internet?). No he tocado nada."; return 1; }

    # 1) ¿Algo que no sea data/state.json modificado a mano? Entonces paramos antes de tocar nada.
    local SUCIOS; SUCIOS="$(git -c core.fileMode=false status --porcelain --untracked-files=no | awk '{print $2}' | grep -vx 'data/state.json')"
    if [ -n "$SUCIOS" ]; then
        echo "❌ Tienes cambios locales sin guardar en:"; echo "$SUCIOS" | sed 's/^/     /'
        echo "   Descártalos con 'git checkout -- <archivo>' (o guárdalos) y vuelve a ejecutar. No he tocado nada."
        return 1
    fi
    # 2) ¿Commits locales (los que hacía la versión antigua de los estados)? Solo vale si únicamente tocan state.json.
    local LOCALES; LOCALES="$(git rev-list --count '@{u}..HEAD')"
    if [ "$LOCALES" -gt 0 ]; then
        local OTROS; OTROS="$(git diff --name-only '@{u}...HEAD' | grep -vx 'data/state.json')"
        if [ -n "$OTROS" ]; then
            echo "❌ Tienes $LOCALES commit(s) locales con cambios en código ($(echo "$OTROS" | tr '\n' ' '))."
            echo "   No los descarto yo solo: revísalos con 'git log @{u}..HEAD'. No he tocado nada."
            return 1
        fi
        echo "ℹ️  Hay $LOCALES commit(s) locales antiguos solo de estado: se descartarán (el estado se conserva en la copia)."
    fi

    local OLD NEW; OLD="$(git rev-parse HEAD)"; NEW="$(git rev-parse '@{u}')"
    if [ "$OLD" = "$NEW" ] && [ "$FORZAR" -eq 0 ] && [ "$LOCALES" -eq 0 ]; then
        echo "✅ Ya tienes la última versión ($(git rev-parse --short HEAD)). No hace falta reiniciar nada."
        return 0
    fi

    # 3) Parar el servicio (al parar, el bot sube su estado a GitHub) y guardar una copia del estado local.
    echo "⏹  Parando el servicio '$SERVICE'..."
    $SUDO systemctl stop "$SERVICE" || { echo "❌ No he podido parar el servicio '$SERVICE'."; return 1; }
    local FALLO_SUBIDA=0
    journalctl -u "$SERVICE" --since "1 minute ago" --no-pager 2>/dev/null | grep -q "Aviso al subir el estado" && FALLO_SUBIDA=1
    mkdir -p "$BACKUPS"
    local COPIA="$BACKUPS/state-$(date +%Y%m%d-%H%M%S).json"
    [ -f data/state.json ] && cp data/state.json "$COPIA" && echo "💾 Copia del estado: $COPIA"
    ls -1t "$BACKUPS"/state-*.json 2>/dev/null | tail -n +11 | xargs -r rm -f   # solo se guardan las 10 últimas

    # 4) Traer la versión nueva. El estado local se descarta porque ya está en GitHub (lo subió el bot al parar);
    #    si esa subida falló, se restaura la copia local, que entonces es la más reciente.
    git checkout -q -- data/state.json 2>/dev/null
    if ! git pull --rebase -q; then
        echo "⚠️  El 'git pull' ha dado conflicto: uso el método de rescate (descartar lo local y quedarme con GitHub)."
        git rebase --abort >/dev/null 2>&1
        git reset -q --hard '@{u}' || { echo "❌ No he podido actualizar el código."; _reiniciar "$SUDO" "$SERVICE"; return 1; }
    elif [ "$LOCALES" -gt 0 ] && [ "$(git rev-list --count '@{u}..HEAD')" -gt 0 ]; then
        git reset -q --hard '@{u}'
    fi
    if [ "$FALLO_SUBIDA" -eq 1 ] && [ -f "$COPIA" ]; then
        cp "$COPIA" data/state.json
        echo "ℹ️  La subida del estado a GitHub había fallado: conservo tu copia local."
    elif [ "$LOCALES" -gt 0 ] && [ -f "$COPIA" ]; then
        cp "$COPIA" data/state.json
        echo "ℹ️  Estado restaurado desde la copia local."
    fi
    local AHORA; AHORA="$(git rev-parse HEAD)"

    # 5) Dependencias, solo si requirements.txt cambió.
    if ! git diff --quiet "$OLD" "$AHORA" -- requirements.txt 2>/dev/null; then
        echo "📦 requirements.txt ha cambiado: instalando dependencias..."
        $PIP install -q -r requirements.txt || echo "⚠️  La instalación de dependencias dio avisos; sigo."
    fi

    # 6) ¿El código nuevo al menos compila?
    if ! $PY -m py_compile check.py 2>/tmp/actualizar-compila.txt; then
        echo "❌ La versión nueva de check.py tiene un error y no arrancaría:"; sed 's/^/     /' /tmp/actualizar-compila.txt
        _volver "$OLD" "$COPIA" "$SUDO" "$SERVICE"; return 1
    fi

    # 7) Arrancar y comprobar que sigue vivo.
    echo "▶️  Arrancando el servicio..."
    local T0; T0="$(date '+%Y-%m-%d %H:%M:%S')"
    $SUDO systemctl start "$SERVICE" || { echo "❌ No arranca."; _volver "$OLD" "$COPIA" "$SUDO" "$SERVICE"; return 1; }
    sleep "$ESPERA"
    local ERRORES; ERRORES="$(journalctl -u "$SERVICE" --since "$T0" --no-pager 2>/dev/null | grep -E "Traceback|SyntaxError|ModuleNotFoundError" | head -3)"
    if ! systemctl is-active --quiet "$SERVICE" || [ -n "$ERRORES" ]; then
        echo "❌ El bot no se mantiene en marcha con la versión nueva."
        [ -n "$ERRORES" ] && { echo "$ERRORES" | sed 's/^/     /'; }
        _volver "$OLD" "$COPIA" "$SUDO" "$SERVICE"; return 1
    fi

    # 8) Resumen.
    echo
    if [ "$OLD" != "$AHORA" ]; then
        echo "✅ Actualizado: $(git rev-parse --short "$OLD") → $(git rev-parse --short "$AHORA")"
        git log --format='   • %s' "$OLD..$AHORA" | head -8
    else
        echo "✅ Reiniciado sin cambios de código ($(git rev-parse --short HEAD))."
    fi
    echo
    echo "📜 Últimas líneas del registro:"
    journalctl -u "$SERVICE" -n 6 --no-pager 2>/dev/null | cut -c1-160 | sed 's/^/   /'
    return 0
}

_reiniciar() { $1 systemctl start "$2" >/dev/null 2>&1; }

# Vuelve a la versión anterior y deja el bot funcionando como estaba.
_volver() {
    local OLD="$1" COPIA="$2" SUDO="$3" SERVICE="$4"
    echo "↩️  Volviendo a la versión anterior ($(git rev-parse --short "$OLD"))..."
    $SUDO systemctl stop "$SERVICE" >/dev/null 2>&1
    git reset -q --hard "$OLD"
    [ -n "$COPIA" ] && [ -f "$COPIA" ] && cp "$COPIA" data/state.json
    $SUDO systemctl start "$SERVICE"
    sleep 3
    if systemctl is-active --quiet "$SERVICE"; then
        echo "✅ El bot vuelve a funcionar con la versión anterior. La nueva sigue en GitHub: pásame el error de arriba."
    else
        echo "⚠️  El servicio no arranca ni con la versión anterior: mira 'journalctl -u $SERVICE -n 30 --no-pager'."
    fi
}

main "$@"
exit $?
