from abc import ABC, abstractmethod
from typing import AsyncGenerator
from app.models.canonical import ChatRequest, ChatResponse, ChatResponseChunk, ModelList


class AIProvider(ABC):
    @abstractmethod
    async def list_models(self) -> ModelList:
        """Return models supported by this upstream provider."""
        ...

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Execute a non-streaming chat completion."""
        ...

    @abstractmethod
    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[ChatResponseChunk, None]:
        """Stream chat completion chunks via SSE."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify provider availability."""
        ...
