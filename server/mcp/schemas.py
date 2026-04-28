from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- resolve_context ----------

class ResolveContextIn(BaseModel):
    url: str = Field(description="A Pivot URL copied from the Web, e.g. https://pivot.enclaws.ai/m/auth-redesign/f/005_xxx.md")


class AvailableTransition(BaseModel):
    to: str = Field(description="Target status this matter can transition to from its current status.")
    trigger_type: str = Field(description="The file type that must be used to trigger this transition (one of: act, think, result, insight).")
    label: str = Field(description="Short human-readable label of this transition (e.g., '开始执行', '暂停', '完成', '取消', '复盘归档'). AI MAY show this verbatim when asking the user whether to attach a status_change.")


class MatterSnapshot(BaseModel):
    id: str
    title: str
    current_status: str
    updated_at: str
    available_transitions: list[AvailableTransition] = Field(
        default_factory=list,
        description=(
            "Legal status transitions from current_status, each with the file type required to trigger it. "
            "BEFORE calling create_file, if this list is non-empty, the AI MUST ask the user whether to "
            "attach a status_change. Never silently attach, never silently skip — let the user decide."
        ),
    )


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
    from_: str = Field(
        alias="from",
        description="Must equal matter.current_status; otherwise backend returns 422 status_change_from_mismatch.",
    )
    to: str = Field(
        description=(
            "Target status. Must equal one of matter_snapshot.available_transitions[].to, "
            "AND the file's `type` must equal that transition's required trigger_type."
        ),
    )

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
    status_change: StatusChangeIn | None = Field(
        default=None,
        description=(
            "OPTIONAL status transition to attach with this file. "
            "PROTOCOL: BEFORE calling create_file, if matter_snapshot.available_transitions is non-empty, "
            "the AI MUST explicitly ask the user whether to attach a status transition — show the user "
            "each option's label + target status, and let the user choose. "
            "Set this field ONLY after the user explicitly opts in; otherwise leave it null. "
            "Never silently attach, never silently skip."
        ),
    )


class CreateFileOut(BaseModel):
    ok: bool
    file_path: str
    view_url: str
    summary_for_ai: str = Field(
        description="A human-friendly confirmation message the AI MUST relay verbatim to the user."
    )


# ---------- create_matter ----------

class CreateMatterIn(BaseModel):
    category: str = Field(
        description="Matter category, e.g. 'Pivot'. Used for on-disk placement under discussions/<category>/<slug>/.",
    )
    title: str = Field(
        description="Matter title. Backend generates the matter_id (slug) from this; collisions are auto-disambiguated with a timestamp suffix.",
    )
    type: str = Field(
        description="First timeline file type. Typically 'think'; backend's planning-state validator rejects types other than think/act for the initial file.",
    )
    summary: str = Field(
        description="One-line summary of the matter, surfaced in list views.",
    )
    body: str = Field(
        default="",
        description="Markdown body of the first timeline file.",
    )
    owner: str | None = Field(
        default=None,
        description="Optional owner pinyin. Leave null to default to the creator.",
    )


class CreateMatterOut(BaseModel):
    ok: bool
    matter_id: str
    category: str
    title: str
    view_url: str
    first_file: str
    summary_for_ai: str = Field(
        description="A human-friendly confirmation message the AI MUST relay verbatim to the user."
    )
