from abc import ABC, abstractmethod

from services.publisher.models import PublicationReference, PublishResult


class PublisherInterface(ABC):

    @abstractmethod
    def publish(
        self,
        content: PublicationReference,
    ) -> PublishResult:
        pass
