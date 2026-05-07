from __future__ import annotations

from typing import Literal

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


# ---------- visibility (shared) ----------


class VisibilityScopeIn(BaseModel):
    """Matter-level visibility scope, mirroring the backend's wire format.

    Empty restricted scope (no roles, no user_ids) is allowed at this layer —
    the backend rejects it implicitly via `visibility_excludes_required_user`
    when the creator/owner can't be admitted, and we surface that 422 verbatim.
    """

    mode: Literal["public", "restricted"] = "public"
    roles: list[str] = Field(
        default_factory=list,
        description="Role names allowed to see the matter when mode='restricted'.",
    )
    user_ids: list[str] = Field(
        default_factory=list,
        description="User open_ids individually allowed when mode='restricted'.",
    )


class CategoryVisibilityIn(BaseModel):
    """Category-level visibility, only used at category creation time."""

    mode: Literal["public", "restricted"] = "public"
    authorized_roles: list[str] = Field(
        default_factory=list,
        description="Role names allowed to see this category when mode='restricted'.",
    )


# ---------- list_matters ----------

class ListMattersIn(BaseModel):
    status: str | None = None
    owner: str | None = None
    q: str | None = None
    filter: Literal["all", "mine"] = Field(
        default="all",
        description=(
            "Relevance filter for the calling user. 'mine' returns only "
            "matters with unread items relevant to you (file-level hits like "
            "owner_assigned / replies to your files / verify of your work / "
            "activity in your matters / mentions of you). 'mine' is NOT "
            "'matters you created or own' — it tracks unread relevance, "
            "not authorship. Default 'all'."
        ),
    )


class MatterListItem(BaseModel):
    id: str
    title: str
    current_status: str
    updated_at: str
    file_count: int | None = None
    owner: str | None = None
    summary: str | None = Field(
        default=None,
        description="Latest timeline file's summary — lets the AI judge relevance without an extra get_matter call per item.",
    )


class ListMattersOut(BaseModel):
    items: list[MatterListItem]


# ---------- get_matter ----------

class GetMatterIn(BaseModel):
    matter_id: str


class TimelineItem(BaseModel):
    """Timeline entries returned by get_matter.

    Two shapes are valid:
    - file entries: type in think/act/verify/result/insight, with file/creator/owner/summary.
    - event entries: type == owner_change, with actor/from_owner/to_owner/reason and no file.
    """

    type: Literal["think", "act", "verify", "result", "insight", "owner_change"]
    created_at: str
    file: str | None = None
    creator: str | None = None
    owner: str | None = None
    summary: str | None = None
    quote: str | None = None
    refer: list[str] = []
    verifications: list[dict] | None = None
    outcome: str | None = None
    status_change: dict | None = None
    actor: str | None = None
    from_owner: str | None = None
    to_owner: str | None = None
    reason: str | None = Field(
        default=None,
        description="For type=owner_change, the required human reason for the transfer.",
    )
    mentions: list[dict] | None = Field(
        default=None,
        description="Mentions (留言 + @ 提醒) attached to this file (each with author_display, body, targets_display). Surfaces discussion the AI would otherwise miss.",
    )
    annotations: list[dict] | None = Field(
        default=None,
        description="Evaluation annotations attached to this file (each with author_display, type, body). v1 only type='evaluation'. Stakeholder DMs are sent server-side; AI-computed scoring fields (rating/weight/...) live separately and are not in this list.",
    )


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


class MentionIn(BaseModel):
    """One @-mention block attached to a file or matter creation.

    The MCP layer keeps mentions flat (single block) to mirror the Web's
    `MentionField` UX — most natural-language requests are "@ a few people
    with one shared message". The MCP tool body translates this into the
    backend's nested `comments: [{body, mentions}]` shape on the way out.
    """

    targets: list[str] = Field(
        min_length=1,
        description=(
            "People to @-mention. Each entry can be the user's pinyin, display "
            "name, or open_id — the backend resolves whichever form it gets. "
            "Unresolvable entries cause a 422 so the AI can ask the user to "
            "correct them; never silently drop names."
        ),
    )
    say: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "One-line message delivered to the mentioned users (Feishu DM "
            "and Matter detail page). Required whenever `targets` is non-empty."
        ),
    )


class CreateFileIn(BaseModel):
    matter_id: str
    type: str  # think | act | verify | result | insight
    summary: str
    body: str = ""
    quote: str | None = Field(
        default=None,
        description=(
            "OPTIONAL. Single matter file path that THIS file directly "
            "replies to / quotes from — equivalent to clicking '回复 X' on "
            "a card in the Web UI. Path must be one of the timeline file "
            "paths returned by `get_matter` (e.g. "
            "'discussions/<category>/<slug>/002_xxx_think_abc.md'). "
            "Set this when the user phrases the request as a reply: "
            "\"回复 X 那条\", \"针对 002 说几句\", \"在 X 基础上跟一条\", "
            "\"reply to <file>\". Use the LATEST file in the timeline as "
            "the default reply target unless the user names a specific one. "
            "Distinct from `refer`: `quote` is exactly one strong, direct "
            "reply target; `refer` is a multi-select context list. "
            "Leave null for a top-level new entry that doesn't reply to "
            "anything specific."
        ),
    )
    refer: list[str] | None = Field(
        default=None,
        description=(
            "OPTIONAL. List of matter file paths used as supporting context "
            "for this file. Up to 4 entries (matches Web MAX_REFER). Paths "
            "must come from `get_matter`'s timeline. "
            "Set this ONLY when the user EXPLICITLY names files to reference: "
            "\"参考一下 001 和 003 来写\", \"把 X 和 Y 一起带着\", \"附上对 X "
            "的引用\". Do NOT auto-populate refer by inferring from the body "
            "text — mentioning a topic that happens to overlap with another "
            "file is NOT a signal to add it. False references pollute the "
            "matter graph. "
            "Special case: when `type='verify'`, `refer[]` doubles as a "
            "cross-matter whitelist — a `verifications[].target` outside the "
            "current matter's timeline is only accepted if it appears in "
            "`refer[]`. The user (not the AI) is responsible for that whitelist. "
            "Leave null/empty unless the user explicitly listed references."
        ),
    )
    owner: str | None = Field(
        default=None,
        description=(
            "OPTIONAL. Almost never needed. Backend auto-fills the owner from "
            "the authenticated user (= the creator of this file). Only set "
            "this when the user EXPLICITLY asks for someone ELSE to own the "
            "file (e.g. '让 X 当 owner'). NEVER ask the user for their own "
            "pinyin to fill this field — leave it null and the backend takes "
            "care of it."
        ),
    )
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
    mentions: MentionIn | None = Field(
        default=None,
        description=(
            "OPTIONAL @-mention block. PROTOCOL: only set this when the user "
            "explicitly asks to notify someone (e.g. '通知 X' / '找 X review' / "
            "'圈 X'). Names that merely appear in the body are NOT a signal to "
            "auto-mention. Always present the resolved targets + `say` line to "
            "the user in chat for confirmation before calling."
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
        description=(
            "OPTIONAL. Almost never needed. Backend auto-fills the owner from "
            "the authenticated user (= the creator of this matter). Only set "
            "this when the user EXPLICITLY asks for someone ELSE to own the "
            "matter (e.g. '让 X 当 owner'). NEVER ask the user for their own "
            "pinyin to fill this field — leave it null and the backend takes "
            "care of it."
        ),
    )
    mentions: MentionIn | None = Field(
        default=None,
        description=(
            "OPTIONAL @-mention block attached to the first timeline file. "
            "PROTOCOL: only set this when the user explicitly asks to notify "
            "someone (e.g. '通知 X' / '找 X review' / '圈 X'). Names appearing "
            "in the body are NOT a signal to auto-mention. Always present the "
            "resolved targets + `say` line to the user for confirmation before "
            "calling."
        ),
    )
    visibility: VisibilityScopeIn | None = Field(
        default=None,
        description=(
            "OPTIONAL matter-level visibility. PROTOCOL: only set when the "
            "user EXPLICITLY says to limit access (e.g. '只给 dev 看', "
            "'限制可见范围', '不要让 X 看到'); otherwise leave null and the "
            "backend defaults to public. Do NOT infer from the body text. "
            "Before setting `mode='restricted'`, call `list_visibility_options` "
            "to fetch the candidate roles/users for the target category, then "
            "echo the resolved scope back to the user for confirmation."
        ),
    )
    new_category_visibility: CategoryVisibilityIn | None = Field(
        default=None,
        description=(
            "OPTIONAL category-level visibility, ONLY needed when (a) the "
            "`category` does not yet exist AND (b) the matter `visibility` is "
            "restricted. Backend returns 422 `missing_category_visibility` "
            "if absent in that scenario. Leave null in every other case."
        ),
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


# ---------- add_mention ----------

class AddMentionIn(BaseModel):
    """Append a mention (留言 + 可选 @ 提醒) to an EXISTING file in a matter.

    Distinct from `create_file` (creates a new timeline item) and from
    `create_matter`'s `mentions` (which rides on the initial file). This is
    the equivalent of clicking the "@ 提及" button on an already-existing
    file card in the Web UI.
    """

    matter_id: str = Field(
        description="ID of the matter that owns the target file. Get from resolve_context / list_matters / get_matter.",
    )
    target_file: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Full file path within the matter (e.g. "
            "'discussions/Pivot/some-slug/003_alice_think_abc.md'). Call "
            "get_matter first to look up which files exist."
        ),
    )
    body: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "Mention text (留言). If `targets` is set, this same text becomes "
            "the @ DM message delivered to those targets — i.e. body doubles as 'say'."
        ),
    )
    targets: list[str] | None = Field(
        default=None,
        description=(
            "OPTIONAL list of @ targets (pinyin / name / open_id). Backend "
            "resolves; unresolvable entries cause 422. Omit / null for a "
            "plain note without notification."
        ),
    )


class AddMentionOut(BaseModel):
    ok: bool
    matter_id: str
    target_file: str
    at: str = Field(description="ISO timestamp the mention was recorded at.")
    view_url: str
    summary_for_ai: str = Field(
        description="A human-friendly confirmation message the AI MUST relay verbatim to the user."
    )


# ---------- add_annotation ----------

class AddAnnotationIn(BaseModel):
    """Append a structured evaluation annotation to an EXISTING file in a matter.

    Distinct from `add_mention` (留言 + @): annotations are first-class
    evaluations on a file (e.g. "verify 不够细致, 建议补一组 edge case").
    There are NO @-targets — the file's stakeholders (creator, matter
    owner, matter creator) are notified by DM automatically. v1 only
    supports type='evaluation'.

    AI-computed scoring inputs (rating, weight, dimension, sentiment,
    score_delta) are explicitly NOT writable here; the backend rejects
    them with 422. Stick to `body` for the natural-language evaluation.
    """

    matter_id: str = Field(
        description="ID of the matter that owns the target file. Get from resolve_context / list_matters / get_matter.",
    )
    target_file: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Full file path within the matter (e.g. "
            "'discussions/Pivot/some-slug/003_alice_verify_abc.md'). Call "
            "get_matter first to look up which files exist."
        ),
    )
    type: Literal["evaluation"] = Field(
        default="evaluation",
        description="Annotation flavor; v1 only supports 'evaluation'.",
    )
    body: str = Field(
        min_length=1,
        max_length=2000,
        description="The evaluation text in natural language.",
    )


class AddAnnotationOut(BaseModel):
    ok: bool
    matter_id: str
    target_file: str
    at: str = Field(description="ISO timestamp the annotation was recorded at.")
    view_url: str
    summary_for_ai: str = Field(
        description="A human-friendly confirmation message the AI MUST relay verbatim to the user."
    )


# ---------- list_visibility_options ----------


class ListVisibilityOptionsIn(BaseModel):
    category: str | None = Field(
        default=None,
        description=(
            "OPTIONAL category id. When provided AND the category is "
            "restricted, the returned roles/users list is filtered to only "
            "what's compatible with that category's authorized_roles. Leave "
            "null to list everything visible to the calling user."
        ),
    )


class ListVisibilityOptionsOut(BaseModel):
    """Mirrors backend `/api/visibility-options` response."""

    all: dict
    roles: list[dict]
    users: list[dict]
