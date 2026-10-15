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


def test_system_reinstall_preserves_existing_config_unless_environment_overrides():
    installer = (ROOT / "installer" / "install.sh").read_text()
    config_load = installer.index('if [ "$MODE" = system ] && [ -r "$CONFIG_DIR/m-group.env" ]; then')
    prompt_start = installer.index('# Interactive setup for headless/server installs.')
    config_write = installer.index('cat > "$ENV_FILE" <<EOF')
    for key in ("M_GROUP_PREFIX", "M_GROUP_DATA_DIR", "M_GROUP_HOST", "M_GROUP_PORT", "M_GROUP_ADMIN_TOKEN"):
        assert f"sed -n 's/^{key}=//p'" in installer
    assert config_load < prompt_start < config_write
    assert 'M_GROUP_PREFIX=$PREFIX' in installer
    # The config-loading block parses known values rather than executing the
    # existing environment file as shell code.
    loading_block = installer[config_load:prompt_start]
    assert '. "$CONFIG_DIR/m-group.env"' not in loading_block



def test_system_installer_initializes_database_before_optional_service_start():
    installer = (ROOT / "installer" / "install.sh").read_text()
    initialize = installer.index('"$BIN_DIR/m-group" init')
    service_registration = installer.index('if [ "${M_GROUP_SKIP_SERVICE:-0}" != 1 ] && command -v systemctl')
    pin_cleanup = installer.index("sed -i '/^M_GROUP_CASHIER_OPERATOR_PIN=/d' \"$ENV_FILE\"")
    assert initialize < service_registration
    assert initialize < pin_cleanup < service_registration
    assert "M_GROUP_SKIP_SERVICE=1" in installer


def test_upgrade_script_takes_verified_database_backup_before_package_upgrade():
    script = (ROOT / "installer" / "upgrade.sh").read_text()
    backup = script.index("source.backup(target)")
    integrity = script.index('PRAGMA integrity_check')
    pip_upgrade = script.index('"$PYTHON" -m pip install --upgrade')
    assert backup < integrity < pip_upgrade
    assert "M-Group_PRE_UPGRADE_" in script
    assert 'os.chmod(backup_path, 0o600)' in script
    assert 'source_path + "?mode=ro"' in script
    assert 'refusing to upgrade without a verified pre-upgrade snapshot' in script
    assert 'exit 1' in script


def test_upgrade_script_shell_syntax():
    result = subprocess.run(
        ["sh", "-n", str(ROOT / "installer" / "upgrade.sh")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

def test_upgrade_script_reads_known_config_values_without_sourcing():
    script = (ROOT / "installer" / "upgrade.sh").read_text()
    assert "read_config_value()" in script
    for key in ("M_GROUP_PREFIX", "M_GROUP_DATA_DIR", "M_GROUP_DB_PATH"):
        assert f"read_config_value {key}" in script
    assert '. "$CONFIG_DIR/m-group.env"' not in script
    assert "PREFIX_OVERRIDE" in script
    assert "DATA_OVERRIDE" in script
    assert "DB_OVERRIDE" in script

