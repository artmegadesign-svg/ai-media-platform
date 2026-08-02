from abc import ABC, abstractmethod

from models.channel_content import ChannelContent

from services.publisher.models import PublishResult


class PublisherInterface(ABC):

    @abstractmethod
    def publish(
        self,
        content: ChannelContent,
    ) -> PublishResult:
        pass
