from pydantic import BaseModel


class StateYamlConfig(BaseModel):
    file: str
    trades_file: str
