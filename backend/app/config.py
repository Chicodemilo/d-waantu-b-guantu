from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_DATABASE: str = "local_agent_tracker"
    MYSQL_USER: str = "lat_user"
    MYSQL_PASSWORD: str = "lat_dev_password"
    MYSQL_ROOT_PASSWORD: str = "lat_root_password"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = True
    ADMIN_API_KEY: str = "lat-admin-CHANGE-ME-TO-RANDOM-64-CHAR-HEX"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
