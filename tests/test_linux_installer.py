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
