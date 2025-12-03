from dotenv import load_dotenv
from pydantic_settings import BaseSettings

from minitap.mobile_use.utils.logger import get_logger

load_dotenv(verbose=True)
logger = get_logger(__name__)


class ServerSettings(BaseSettings):
    ADB_HOST: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


server_settings = ServerSettings()
