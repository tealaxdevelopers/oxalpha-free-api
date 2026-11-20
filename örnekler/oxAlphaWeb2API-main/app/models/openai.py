import logging
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.canonical import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatResponseChunk,
    ModelList,
    ModelCard,
    UsageInfo,
)

logger = logging.getLogger(__name__)


class OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: Union[str, List[Dict[str, Any]]]
    name: Optional[str] = None

    def get_text_content(self) -> str:
        """Extract flat text from content (handling multipart or string)."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            parts = []
            for part in self.content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif "content" in part:
                        parts.append(str(part.get("content", "")))
                else:
                    parts.append(str(part))
            return "".join(parts)
        return str(self.content)


class OpenAIChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: List[OpenAIMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    user: Optional[str] = None

    # Unsupported parameters that fundamentally alter semantics
    tools: Optional[List[Any]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    functions: Optional[List[Any]] = None
    function_call: Optional[Union[str, Dict[str, Any]]] = None
    response_format: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_semantics(self) -> "OpenAIChatCompletionRequest":
        if self.tools:
            raise ValueError("Tool calling ('tools') is not supported by the OxAlpha upstream interface.")
        if self.functions:
            raise ValueError("Function calling ('functions') is not supported by the OxAlpha upstream interface.")
        if self.response_format and self.response_format.get("type") == "json_object":
            logger.debug("json_object response_format requested; OxAlpha upstream operates in markdown/plaintext mode.")
        if self.presence_penalty is not None or self.frequency_penalty is not None:
            logger.debug("presence_penalty/frequency_penalty ignored gracefully.")
        return self

    def to_canonical(self) -> ChatRequest:
        canonical_messages = [
            ChatMessage(
                role=m.role,
                content=m.get_text_content(),
                name=m.name
            )
            for m in self.messages
        ]
        return ChatRequest(
            model=self.model,
            messages=canonical_messages,
            stream=bool(self.stream),
            temperature=self.temperature,
            top_p=self.top_p,
            stop=self.stop,
            max_tokens=self.max_tokens,
            user=self.user,
        )


class OpenAIUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatCompletionChoice(BaseModel):
    index: int = 0
    message: OpenAIMessage
    finish_reason: Optional[str] = "stop"


class OpenAIChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[OpenAIChatCompletionChoice]
    usage: OpenAIUsage = Field(default_factory=OpenAIUsage)

    @classmethod
    def from_canonical(cls, res: ChatResponse) -> "OpenAIChatCompletionResponse":
        return cls(
            id=res.id,
            object=res.object,
            created=res.created,
            model=res.model,
            choices=[
                OpenAIChatCompletionChoice(
                    index=c.index,
                    message=OpenAIMessage(role=c.message.role, content=c.message.content, name=c.message.name),
                    finish_reason=c.finish_reason,
                )
                for c in res.choices
            ],
            usage=OpenAIUsage(
                prompt_tokens=res.usage.prompt_tokens,
                completion_tokens=res.usage.completion_tokens,
                total_tokens=res.usage.total_tokens,
            ),
        )


class OpenAIChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class OpenAIChunkChoice(BaseModel):
    index: int = 0
    delta: OpenAIChunkDelta
    finish_reason: Optional[str] = None


class OpenAIChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[OpenAIChunkChoice]
    usage: Optional[OpenAIUsage] = None

    @classmethod
    def from_canonical(cls, chunk: ChatResponseChunk) -> "OpenAIChatCompletionChunk":
        usage = None
        if chunk.usage:
            usage = OpenAIUsage(
                prompt_tokens=chunk.usage.prompt_tokens,
                completion_tokens=chunk.usage.completion_tokens,
                total_tokens=chunk.usage.total_tokens,
            )
        return cls(
            id=chunk.id,
            object=chunk.object,
            created=chunk.created,
            model=chunk.model,
            choices=[
                OpenAIChunkChoice(
                    index=c.index,
                    delta=OpenAIChunkDelta(role=c.delta.role, content=c.delta.content),
                    finish_reason=c.finish_reason,
                )
                for c in chunk.choices
            ],
            usage=usage,
        )


class OpenAIModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int = 1700000000
    owned_by: str = "oxalpha"


class OpenAIModelList(BaseModel):
    object: str = "list"
    data: List[OpenAIModelCard]

    @classmethod
    def from_canonical(cls, models: ModelList) -> "OpenAIModelList":
        return cls(
            object=models.object,
            data=[
                OpenAIModelCard(
                    id=m.id,
                    object=m.object,
                    created=m.created,
                    owned_by=m.owned_by,
                )
                for m in models.data
            ],
        )
