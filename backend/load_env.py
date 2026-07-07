"""Tiny .env loader + credential resolution shared across the backend.

No external dependency. Loads KEY=VALUE lines from backend/.env into the
environment (without overriding anything already set), and resolves the Kalshi
private key from either inline PEM or a path to a .pem file.
"""
import os

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def load_dotenv(path=ENV_PATH):
    """Load KEY=VALUE lines from `path` into os.environ (no overrides)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Support single-line PEMs written with literal \n escapes.
            os.environ.setdefault(key, val.replace("\\n", "\n"))


def resolve_private_key(value):
    """Return PEM text. Accepts the PEM content directly, or a path to a .pem
    file (handy for the multi-line RSA key)."""
    if not value:
        return value
    if "BEGIN" not in value and os.path.isfile(value):
        with open(value) as f:
            return f.read()
    return value.replace("\\n", "\n")
