from pydantic import BaseModel


class TelegramYamlConfig(BaseModel):
    enable: bool = False
    chat_id: int
