#!/bin/sh
# Install a checkout without pip, a virtualenv, or downloaded Python dependencies.
set -eu

prefix="${PREFIX:-$HOME/.local}"
python="${PYTHON:-python3}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix|--python)
            if [ "$#" -lt 2 ]; then echo "Missing value for $1" >&2; exit 2; fi
            if [ "$1" = "--prefix" ]; then prefix="$2"; else python="$2"; fi
            shift 2 ;;
        --help|-h)
            echo "Usage: sh scripts/install.sh [--prefix DIRECTORY] [--python EXECUTABLE]"
            echo "Default prefix: \$HOME/.local. Requires Python 3.11+ and tmux."
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

"$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "tcar requires Python 3.11+")'
prefix=$("$python" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$prefix")
if ! command -v tmux >/dev/null 2>&1; then
    echo "tcar requires tmux. Install it with brew install tmux or your Linux package manager." >&2
    exit 1
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
"$python" "$root/scripts/build_release.py" --output-dir "$work" >/dev/null
mkdir -p "$prefix/bin" "$prefix/share/tcar"
cp "$work/tcar.pyz" "$prefix/share/tcar/.tcar-install.pyz"
mv "$prefix/share/tcar/.tcar-install.pyz" "$prefix/share/tcar/tcar.pyz"

# Pin the launcher to the selected interpreter, including paths containing spaces.
"$python" - "$prefix" <<'PY'
from pathlib import Path
import os
import shlex
import sys

prefix = Path(sys.argv[1]).expanduser().resolve()
application = prefix / "share" / "tcar" / "tcar.pyz"
launcher = prefix / "bin" / "tcar"
staged = launcher.with_name(".tcar-install")
staged.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(application)) + ' "$@"\n')
staged.chmod(0o755)
os.replace(staged, launcher)
print(f"Installed {launcher}")
print(f"Try: {shlex.quote(str(launcher))} --demo")
print(f"Create config: {shlex.quote(str(launcher))} --init-config")
print(f"Add {shlex.quote(str(prefix / 'bin'))} to PATH if needed.")
PY
