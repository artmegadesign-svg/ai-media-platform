import requests
from services.publisher.interface import PublisherInterface
from services.publisher.models import PublishResult


class TelegramPublisher(PublisherInterface):

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def publish(self, content):

        text = content.post.ru_content

        url = (
            f"https://api.telegram.org/"
            f"bot{self.token}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": self.chat_id,
                "text": text,
            },
            timeout=10,
        )

        data = response.json()

        if not data.get("ok"):
            return PublishResult(
                success=False,
                error=str(data),
            )

        return PublishResult(
            success=True,
            platform_post_id=str(
                data["result"]["message_id"]
            )
        )
