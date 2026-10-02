import os

from weather_station_server.config import INGEST_TOKEN_ENV_VAR

os.environ.setdefault(INGEST_TOKEN_ENV_VAR, "test-token")
