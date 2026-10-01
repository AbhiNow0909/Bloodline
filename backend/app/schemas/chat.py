"""Chat with the query agent. The server keeps no chat history: the app sends the conversation
so far with each question, and names in it are replaced by labels before the model sees it."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

DISCLAIMER = (
    "Not medical advice. Bloodline can describe your results, but only your doctor can say "
    "what they mean for you."
)

MAX_MESSAGES = 20
MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: MessageText


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)

    @model_validator(mode="after")
    def ends_with_a_question(self) -> Self:
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be the user's question")
        return self


class ChatSource(BaseModel):
    """A report the answer was based on."""

    report_id: uuid.UUID
    collected_at: datetime
    lab_name: str | None
    member_id: uuid.UUID
    member_name: str


class ChatReply(BaseModel):
    reply: str
    sources: list[ChatSource]
    disclaimer: str = DISCLAIMER
