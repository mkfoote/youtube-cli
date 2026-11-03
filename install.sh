#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
install_dir=${YOUTUBE_CLI_INSTALL_DIR:-"$data_home/youtube-cli"}
bin_dir=${YOUTUBE_CLI_BIN_DIR:-"$HOME/.local/bin"}
python_command=${PYTHON:-python3}
venv_dir="$install_dir/venv"
launcher="$bin_dir/youtube-cli"

"$python_command" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "youtube-cli requires Python 3.10 or newer")'

if [ -e "$launcher" ] && [ ! -L "$launcher" ]; then
    echo "Cannot install: $launcher already exists and is not a symbolic link." >&2
    exit 1
fi

mkdir -p "$install_dir" "$bin_dir"
"$python_command" -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install --upgrade "$project_dir"
ln -sfn "$venv_dir/bin/youtube-cli" "$launcher"

echo "Installed youtube-cli at $launcher"
case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *)
        echo "Add $bin_dir to PATH, then open a new terminal:"
        echo "  export PATH=\"$bin_dir:\$PATH\""
        ;;
esac
echo "Next, run: youtube-cli config"
