from abc import ABC, abstractmethod


class AIProvider(ABC):
    @abstractmethod
    def chat(self, system: str, user: str) -> str:
        pass
