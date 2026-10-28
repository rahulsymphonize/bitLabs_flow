from pydantic import BaseModel, Field


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1)
    type: str = "other"
    description: str = ""


class ExtractedRelation(BaseModel):
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class Extraction(BaseModel):
    """Shape Gemini is asked to return for one chunk."""

    entities: list[ExtractedEntity] = []
    relations: list[ExtractedRelation] = []
