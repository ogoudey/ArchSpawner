#!/usr/bin/env bash
#
# setup_docker.sh — installs Docker Engine if missing, starts the service,
# fixes user-group permissions, and validates the whole stack end to end
# (including the Python `docker` SDK, if a venv is present).
#
# Safe to re-run: every step checks current state first and skips if already
# satisfied. Supports Arch, Debian/Ubuntu, and Fedora/RHEL natively, with a
# fallback to Docker's official convenience script for anything else.
#
# Usage:
#   ./setup_docker.sh              # auto-detects .venv in the current dir
#   ./setup_docker.sh /path/to/venv
#
set -euo pipefail

VENV_PATH="${1:-.venv}"
NEED_RELOGIN=0

# ---- helpers ----------------------------------------------------------
info()  { printf '\033[1;34m[*]\033[0m %s\n' "$1"; }
ok()    { printf '\033[1;32m[✓]\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m[!]\033[0m %s\n' "$1"; }
fail()  { printf '\033[1;31m[✗]\033[0m %s\n' "$1"; exit 1; }

# ---- 0. must not be run as root (we want $USER's real identity) -------
if [[ "${EUID}" -eq 0 ]]; then
    fail "Run this as your normal user, not root — it calls sudo itself where needed."
fi

# ---- 1. detect distro ---------------------------------------------------
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}
DISTRO="$(detect_distro)"
info "Detected distro: ${DISTRO}"

# ---- 2. install Docker Engine, if missing ------------------------------
if command -v docker >/dev/null 2>&1; then
    ok "Docker CLI already installed ($(docker --version))."
else
    info "Docker not found — installing..."
    case "$DISTRO" in
        arch|manjaro|endeavouros)
            sudo pacman -Syu --noconfirm docker
            ;;
        ubuntu|debian|linuxmint|pop)
            sudo apt-get update
            sudo apt-get install -y ca-certificates curl
            curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
            sudo sh /tmp/get-docker.sh
            rm -f /tmp/get-docker.sh
            ;;
        fedora|rhel|centos|rocky|almalinux)
            sudo dnf -y install dnf-plugins-core
            sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo || true
            sudo dnf -y install docker-ce docker-ce-cli containerd.io
            ;;
        *)
            warn "Unrecognized distro '${DISTRO}' — falling back to Docker's official install script."
            curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
            sudo sh /tmp/get-docker.sh
            rm -f /tmp/get-docker.sh
            ;;
    esac
    ok "Docker Engine installed."
fi

# ---- 3. start + enable the daemon --------------------------------------
if systemctl is-active --quiet docker; then
    ok "Docker service already running."
else
    info "Starting and enabling the docker service..."
    sudo systemctl enable --now docker
    ok "Docker service started."
fi

# ---- 4. add user to the docker group -----------------------------------
if id -nG "$USER" | grep -qw docker; then
    ok "User '$USER' already in the docker group."
else
    info "Adding '$USER' to the docker group..."
    sudo usermod -aG docker "$USER"
    NEED_RELOGIN=1
    ok "Added. (Takes effect in new shells / after re-login.)"
fi

# ---- 5. validate docker itself, using the new group without logging out --
info "Validating Docker with a test container..."
if sg docker -c "docker run --rm hello-world" >/tmp/docker_hello.log 2>&1; then
    ok "Docker daemon reachable and working."
else
    cat /tmp/docker_hello.log
    fail "docker run hello-world failed — see output above."
fi
rm -f /tmp/docker_hello.log

# ---- 6. validate the Python SDK, if a venv exists ------------------------
PY_BIN="${VENV_PATH}/bin/python3"
if [[ -x "$PY_BIN" ]]; then
    info "Found venv at '${VENV_PATH}' — checking the Python docker SDK..."
    if sg docker -c "'$PY_BIN' -c \"import docker; print('SDK OK, server version:', docker.from_env().version()['Version'])\"" ; then
        ok "Python docker SDK can reach the daemon."
    else
        warn "Python docker SDK could not connect. Is 'docker' in ${VENV_PATH}'s requirements installed? (pip install -r requirements.txt)"
    fi
else
    warn "No venv found at '${VENV_PATH}' — skipping Python SDK check. Pass a path as \$1 if it's elsewhere."
fi

# ---- 7. summary -----------------------------------------------------------

newgrp docker
echo
if [[ "$NEED_RELOGIN" -eq 1 ]]; then
    warn "Log out and back in (or run 'newgrp docker' in each open terminal) before running the spawner directly — this script validated things via 'sg docker', but your normal shell won't have the new group until then."
else
    ok "All set — Docker is installed, running, and reachable by '$USER'."
fi


