import logging
from typing import Tuple, Type, List, Dict, Optional
import google.oauth2.id_token
import time
from pydantic import Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
import os
os.environ.setdefault("RUN_ENV", "lab")
def get_yaml_file():
    """
    Return the path to the lab.yaml file and validate its existence.
    """
    print(f"Loading configuration for RUN_ENV={os.getenv('RUN_ENV')}")
    
    if 'RUN_ENV' in os.environ:
        env = os.getenv('RUN_ENV')
        print(f"Loading configuration for {env}")
        yaml_path = f"configs/{env}.yaml"
    else:
        raise Exception(
            "CONFIG_PATH not found in the environment variables. Please"
            " set RUN_ENV environment variable following format:"
            " export RUN_ENV=lab"
        )
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"The configuration file {yaml_path} does not exist.")
    
    return yaml_path

class SecureToken:
    def __init__(self, token: str):
        self._token = token

    def __str__(self):
        return "<SecureToken: hidden>"

    def __repr__(self):
        return "<SecureToken: hidden>"

    def get(self) -> str:
        return self._token


class TokenCache:
    def __init__(self):
        self._token = None
        self._expiry = 0

    def get_token(self, audience: str) -> SecureToken:
        if self._token is None or time.time() > self._expiry:
            self._token = google.oauth2.id_token.fetch_id_token(
                google.auth.transport.requests.Request(),
                audience
            )
            self._expiry = time.time() + 300  # Cache for 5 minutes
        return SecureToken(self._token)

class GetConf(BaseSettings):
    """
    Class for wrapping all env variables. This way, there is no need to use
    os.getenv() in the app and the variables can be accessed using this class.

    Also, this helps with the validation of the variables. If one variable is
    missing, it will print a message with the variables that are not configured
    in the env file.
    """

    @staticmethod
    def load_configs():
        """Initialize a settings object to get all the defined variables"""
        try:
            settings = GetConf()
            return settings
        except ValidationError as e:
            logging.error("Missing env variables in .yaml file:")
            for error in e.errors():
                logging.error("- %s: %s", error["loc"][0], error["msg"])
            raise

    # Configure BaseSettings to read variables from yaml file
    model_config = SettingsConfigDict(yaml_file=get_yaml_file())

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return YamlConfigSettingsSource(settings_cls),

    # ---------- VARIABLES FROM RUN_ENV.yaml FILE START----------
    PROJECT_ID: str = Field(..., env="PROJECT_ID")
    REGION: str = Field(..., env="REGION")
    LLM_MODEL: str = Field(..., env="LLM_MODEL")
    BQ_DATASET_ID: str = Field(..., env="BQ_DATASET_ID")
    BQ_TABLE_ID: str = Field(..., env="BQ_TABLE_ID")
    GCS_BUCKET_NAME: str = Field(..., env="GCS_BUCKET_NAME")
    DISABLE_WEB_DRIVER: int = Field(..., env="DISABLE_WEB_DRIVER")
    LLM_PROXY_ENDPOINT: str = Field(..., env="LLM_PROXY_ENDPOINT")
    RUN_AGENT_WITH_DEBUG: bool = Field(..., env="RUN_AGENT_WITH_DEBUG")
    SERVE_WEB_INTERFACE: bool = Field(..., env="SERVE_WEB_INTERFACE")
    SESSION_DB_URL: str = Field(..., env="SESSION_DB_URL")
    EMBEDDING_MODEL_NAME: str = Field(..., env="EMBEDDING_MODEL_NAME")
    # ---------- VARIABLES FROM lab.yaml FILE END ----------
    
    _token_cache = TokenCache()

    @property
    def ID_TOKEN(self) -> SecureToken:
        return self._token_cache.get_token(self.LLM_PROXY_ENDPOINT)

    @property
    def API_BASE(self) -> str:
        return f"{self.LLM_PROXY_ENDPOINT}/google-llm/v1/projects/{self.PROJECT_ID}/locations/{self.REGION}/publishers/google/models/{self.LLM_MODEL}"
