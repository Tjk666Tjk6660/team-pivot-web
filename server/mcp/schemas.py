from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- resolve_context ----------

class ResolveContextIn(BaseModel):
    url: str = Field(description="A Pivot URL copied from the Web, e.g. https://pivot.enclaws.ai/m/auth-redesign/f/005_xxx.md")


class MatterSnapshot(BaseModel):
    id: str
    title: str
    current_status: str
    updated_at: str


class ResolveContextOut(BaseModel):
    matter_id: str
    file_path: str | None
    matter_snapshot: MatterSnapshot
    user_facing_summary: str = Field(
        description="A natural-language summary the AI MUST show to the user verbatim, so the user can verify the correct context was loaded."
    )


# ---------- list_matters ----------

class ListMattersIn(BaseModel):
    status: str | None = None
    owner: str | None = None
    q: str | None = None


class MatterListItem(BaseModel):
    id: str
    title: str
    current_status: str
    updated_at: str
    file_count: int | None = None


class ListMattersOut(BaseModel):
    items: list[MatterListItem]


# ---------- get_matter ----------

class GetMatterIn(BaseModel):
    matter_id: str


class TimelineItem(BaseModel):
    file: str
    created_at: str
    creator: str
    owner: str
    type: str
    summary: str
    quote: str | None = None
    refer: list[str] = []
    verifications: list[dict] | None = None
    outcome: str | None = None
    status_change: dict | None = None


class GetMatterOut(BaseModel):
    matter: MatterSnapshot
    timeline: list[TimelineItem]


# ---------- read_files ----------

class ReadFilesIn(BaseModel):
    matter_id: str
    paths: list[str]


class FileContent(BaseModel):
    file_path: str
    type: str
    creator: str
    owner: str
    created_at: str
    body: str
    truncated: bool = False


class ReadFilesOut(BaseModel):
    files: list[FileContent]


# ---------- create_file ----------

class VerificationIn(BaseModel):
    target: str
    judgement: str  # passed | failed | cancelled
    comment: str


class StatusChangeIn(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class CreateFileIn(BaseModel):
    matter_id: str
    type: str  # think | act | verify | result | insight
    summary: str
    body: str = ""
    quote: str | None = None
    refer: list[str] | None = None
    owner: str | None = None
    verifications: list[VerificationIn] | None = None
    outcome: str | None = None  # finished | cancelled (result only)
    status_change: StatusChangeIn | None = None


class CreateFileOut(BaseModel):
    ok: bool
    file_path: str
    view_url: str
    summary_for_ai: str = Field(
        description="A human-friendly confirmation message the AI MUST relay verbatim to the user."
    )
