import getpass
import os
import stat
from pathlib import Path


class CredentialError(Exception):
    pass


def _check_file_permissions(path: Path) -> None:
    """Raise CredentialError if file permissions are more permissive than 600."""
    mode = path.stat().st_mode
    # Only owner read/write allowed
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        octal = oct(stat.S_IMODE(mode))
        raise CredentialError(
            f"Credentials file {path} has unsafe permissions ({octal}). "
            "Run: chmod 600 " + str(path)
        )


def _parse_creds_file(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise CredentialError(f"Invalid line in credentials file: {line!r}")
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def load_credentials(
    server: str | None,
    username: str | None,
    creds_file: str | None,
) -> tuple[str, str, str]:
    """Return (server, username, password). Never stores password anywhere."""
    parsed = {}
    if creds_file:
        p = Path(creds_file)
        if not p.exists():
            raise CredentialError(f"Credentials file not found: {creds_file}")
        _check_file_permissions(p)
        parsed = _parse_creds_file(p)

    resolved_server = server or parsed.get("server")
    resolved_username = username or parsed.get("username")
    password = parsed.get("password")

    if not resolved_server:
        raise CredentialError("IMAP server not provided. Supply --server or include 'server=' in creds file.")
    if not resolved_username:
        raise CredentialError("Username not provided. Supply --username or include 'username=' in creds file.")

    if not password:
        password = getpass.getpass(f"Password for {resolved_username}@{resolved_server}: ")

    return resolved_server, resolved_username, password
