from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_linux_installer_shell_syntax():
    result = subprocess.run(
        ["sh", "-n", str(ROOT / "installer" / "install.sh")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_linux_installer_defaults_to_all_interfaces_and_prompts_for_configuration():
    installer = (ROOT / "installer" / "install.sh").read_text()
    docs = (ROOT / "installer" / "README.md").read_text()
    assert 'M_GROUP_HOST:-0.0.0.0' in installer
    assert 'if [ "$MODE" = system ] && [ -t 0 ]; then' in installer
    assert "Admin API token (hidden" in installer
    assert 'CONFIG_DIR=${M_GROUP_CONFIG_DIR:-/etc/m-group}' in installer
    assert "/etc/m-group/m-group.env" in docs
    assert "DHCP" in docs
    assert "TLS reverse proxy" in docs
    assert 'chown root:"$SERVICE_USER" "$ENV_FILE"' in installer
    assert 'chmod 0640 "$ENV_FILE"' in installer
    assert 'chown "$SERVICE_USER:$SERVICE_USER" /var/log/m-group.log' in installer
    assert "Initial Cashier operator PIN" in installer
    assert "M_GROUP_CASHIER_OPERATOR_PIN=$OPERATOR_PIN" in installer
    assert 'umask 077' in installer
    assert 'chmod 0750 "$DATA"' in installer
    assert 'if [ -r "$CONFIG_DIR/m-group.env" ]; then' in installer



def test_interactive_custom_prefix_updates_derived_install_paths():
    installer = (ROOT / "installer" / "install.sh").read_text()
    prompt_end = installer.index('case "$HOST" in')
    prefix_prompt = installer.index('Application install directory')
    venv_assignment = installer.index('VENV="$PREFIX/venv"', prefix_prompt)
    bin_assignment = installer.index('BIN_DIR="$PREFIX/bin"', prefix_prompt)
    assert venv_assignment < prompt_end
    assert bin_assignment < prompt_end
    assert installer.rfind('VENV="$PREFIX/venv"', 0, prompt_end) == venv_assignment
    assert installer.rfind('BIN_DIR="$PREFIX/bin"', 0, prompt_end) == bin_assignment


def test_linux_installer_has_supported_prerequisite_bootstrap():
    installer = (ROOT / "installer" / "install.sh").read_text()
    for package_manager in ("apt-get", "apk", "dnf", "yum", "pacman", "zypper"):
        assert package_manager in installer
    assert "python_ok" in installer
    assert "sudo" in installer


def test_linux_installer_documents_automatic_dependencies():
    docs = (ROOT / "installer" / "README.md").read_text()
    assert "automatically" in docs
    assert "postmarketOS" in docs
