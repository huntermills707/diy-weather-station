"""Runtime configuration loaded from the environment (issue #23).

Secrets live outside version control: locally in the gitignored
``server/.env``, and on the Pi in a root-readable EnvironmentFile consumed
by systemd (ADR 0001).
"""

import os
from collections.abc import Mapping

INGEST_TOKEN_ENV_VAR = "WEATHER_STATION_INGEST_TOKEN"


class MissingConfigError(RuntimeError):
    """Raised when required configuration is absent from the environment."""


def load_ingest_token(env: Mapping[str, str] | None = None) -> str:
    """Return the per-station ingest token, failing clearly when unset."""
    env = os.environ if env is None else env
    token = env.get(INGEST_TOKEN_ENV_VAR, "").strip()
    if not token:
        raise MissingConfigError(
            f"{INGEST_TOKEN_ENV_VAR} is not set. Copy server/.env.example to "
            "server/.env, fill in a token, and load it into the environment "
            "(or set the variable directly, or via the systemd EnvironmentFile)."
        )
    return token
