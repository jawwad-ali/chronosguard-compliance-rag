"""RFC 9457 problem+json response shape — the only error contract clients see."""

from pydantic import BaseModel, ConfigDict


class FieldError(BaseModel):
    loc: str
    msg: str
    type: str


class ProblemDetail(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": "Policy not found: 42",
                "instance": "/api/v1/policies/42",
                "request_id": "8a2f0c4e9b1d4f6e8a2f0c4e9b1d4f6e",
            }
        }
    )

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str
    errors: list[FieldError] | None = None
