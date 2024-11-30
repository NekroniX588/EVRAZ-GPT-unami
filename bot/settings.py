import os

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    tg_token: str = '7241545492:AAEbKXJ-XOt0xgFYUr0I2NlzDVisxIpEPaw'
    path_to_projects: str = "./projects/"
    database_name: str = "test_db.db"


settings = Settings()