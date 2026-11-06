from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class HelpdeskWebhookPayload(BaseModel):
    """Payload received from the helpdesk for a newly created ticket."""

    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=128)
    ticket_id: str = Field(min_length=1, max_length=128)
    customer_email: str = Field(min_length=3, max_length=320)
    message: str = Field(min_length=1)
    reply_url: AnyHttpUrl


class HelpdeskWebhookResponse(BaseModel):
    """Acknowledgement returned after the payload is durably stored."""

    accepted: bool
    duplicate: bool


class MockHelpdeskReplyRequest(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1)


class MockHelpdeskReplyResponse(BaseModel):
    ticket_id: str
    accepted: bool
