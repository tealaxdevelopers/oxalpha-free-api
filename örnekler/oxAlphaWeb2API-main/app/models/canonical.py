from typing import List, Optional, Union
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    user: Optional[str] = None


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponseChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: Optional[str] = "stop"


class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatResponseChoice]
    usage: UsageInfo = Field(default_factory=UsageInfo)


class ChatChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class ChatChunkChoice(BaseModel):
    index: int = 0
    delta: ChatChunkDelta
    finish_reason: Optional[str] = None


class ChatResponseChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[ChatChunkChoice]
    usage: Optional[UsageInfo] = None


class ModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int = 1700000000
    owned_by: str = "oxalpha"


class ModelList(BaseModel):
    object: str = "list"
    data: List[ModelCard]
