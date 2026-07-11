"""Pydantic request/response models."""
from pydantic import BaseModel


class VideoPayload(BaseModel):
    videoId: str
    title: str
    channel: str