from abc import ABC, abstractmethod


class BaseGenerator(ABC):
    """
    Base interface for all content generators.
    """

    @abstractmethod
    def generate(self, topic: str) -> dict:
        """
        Generate content from topic.

        Returns:
            dict with generated content data.
        """
        pass
