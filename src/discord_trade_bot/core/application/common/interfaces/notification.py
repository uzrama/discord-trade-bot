from abc import ABC, abstractmethod


class NotificationGatewayProtocol(ABC):
    @abstractmethod
    async def send_message(self, text: str) -> bool:
        pass
