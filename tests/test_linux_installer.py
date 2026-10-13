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


def test_linux_installer_documents_safe_localhost_default():
    installer = (ROOT / "installer" / "install.sh").read_text()
    docs = (ROOT / "installer" / "README.md").read_text()
    assert 'M_GROUP_HOST:-127.0.0.1' in installer
    assert "/etc/m-group/m-group.env" in docs
    assert "SSH tunnel" in docs


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
