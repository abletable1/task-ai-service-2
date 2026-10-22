from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from task_ai_service.postprocessing import normalize_text

InputText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=20, max_length=20000)
]


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: InputText
    max_sentences: int = Field(default=3, ge=1, le=10)

    @field_validator("text")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if len(normalize_text(value)) < 20:
            raise ValueError("Text must contain at least 20 meaningful characters")
        return value


class ProcessResponse(BaseModel):
    summary: str
    source: Literal["gigachat", "fallback"]
    cached: bool = False
    warning: str | None = None
    request_id: str


class ErrorResponse(BaseModel):
    error: str
    request_id: str
