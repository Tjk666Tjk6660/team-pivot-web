from __future__ import annotations

from typing import Any

from server.pivot_users import PivotUser


# Reason codes — order matters: priority is top-down, first match wins.
REASON_OWNER_ASSIGNED = "owner_assigned"
REASON_REPLY_TO_MY_FILE = "reply_to_my_file"
REASON_REPLY_TO_MY_OWNED = "reply_to_my_owned"
REASON_VERIFY_MY_FILE = "verify_my_file"
REASON_IN_MY_MATTER = "in_my_matter"
REASON_IN_MY_OWNED_MATTER = "in_my_owned_matter"


def compute_relevance(
    item: dict[str, Any],
    matter_data: dict[str, Any],
    user: PivotUser,
) -> tuple[bool, str | None]:
    """Decide whether a timeline item is file-level relevant to ``user``.

    Returns ``(is_relevant, reason_code)``. If not relevant, returns
    ``(False, None)``. If relevant, returns the highest-priority matched
    rule's reason. Priority order:

    1. owner_assigned       — someone made me the owner of this file
    2. reply_to_my_file     — item.quote points to a file I created
    3. reply_to_my_owned    — item.quote points to a file I own
    4. verify_my_file       — item.verifications target a file I created/own
    5. in_my_matter         — I authored the matter's first proposal
    6. in_my_owned_matter   — matter.owner is me (matter-level owner field)

    Rules 5 and 6 are both "broad matter-level" signals — every item created
    by someone else inside a matter where I'm the creator (5) or the
    matter-level owner (6) is relevant to me. Rule 5 wins when both match,
    on the rationale that "I created this matter" is a stronger signal than
    "someone assigned me as matter owner". Either reason is correct; only
    the chip label differs in the UI.

    Self-exclusion: if the user authored the item (``item.creator == me``),
    no rule applies — self-triggered actions don't notify the actor.

    Comment-level @ mentions are NOT handled here. ``relevance_writer`` /
    ``relevance_scanner`` directly read ``comment.mentions`` and write rows
    with ``kind='mention'`` / ``reason='comment_mention'``.
    """
    if not user.pinyin:
        return False, None

    me = user.pinyin
    creator = item.get("creator")

    # Self-exclusion: I authored this item — don't notify myself.
    if creator == me:
        return False, None

    # Rule 1: owner_assigned — someone else made me the owner.
    owner = item.get("owner")
    if owner == me:
        return True, REASON_OWNER_ASSIGNED

    # Rule 2/3: this item quotes a file I created or own.
    timeline = matter_data.get("timeline") or []
    item_by_file: dict[str, dict] = {
        it.get("file"): it for it in timeline if it.get("file")
    }

    quote = item.get("quote")
    if quote:
        quoted = item_by_file.get(quote)
        if quoted is not None:
            if quoted.get("creator") == me:
                return True, REASON_REPLY_TO_MY_FILE
            if quoted.get("owner") == me:
                return True, REASON_REPLY_TO_MY_OWNED

    # Rule 4: this item verifies a file I created or own.
    verifications = item.get("verifications") or []
    for v in verifications:
        if not isinstance(v, dict):
            continue
        target = v.get("target")
        if not target:
            continue
        targeted = item_by_file.get(target)
        if targeted is None:
            continue
        if targeted.get("creator") == me or targeted.get("owner") == me:
            return True, REASON_VERIFY_MY_FILE

    # Rule 5: I authored this matter's first proposal.
    if timeline:
        first_creator = timeline[0].get("creator")
        if first_creator == me:
            return True, REASON_IN_MY_MATTER

    # Rule 6: matter-level owner is me. Anything someone else creates in a
    # matter I'm the owner of is mine to follow up on. The matter index'
    # `matter.owner` field is set at the matter level (separate from the
    # per-file owner already covered by rule 1).
    matter_meta = matter_data.get("matter") or {}
    if matter_meta.get("owner") == me:
        return True, REASON_IN_MY_OWNED_MATTER

    return False, None
