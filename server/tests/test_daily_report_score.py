"""Tests for `server.daily_report.score.score_team` — AI happy path,
graceful fallback for every failure mode."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from server.ai.oneshot import AIError
from server.daily_report import score as score_module
from server.daily_report.score import AISettings, score_team
from server.daily_report.types import (
    CommitRecord,
    MatterEvent,
    TeamSummary,
    TimeWindow,
    UserActivity,
)
from server.daily_report.window import CHINA_TZ


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _window():
    return TimeWindow(
        since=datetime(2026, 4, 26, 9, 30, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 27, 9, 30, tzinfo=CHINA_TZ),
    )


def _summary(window=None) -> TeamSummary:
    return TeamSummary(
        window=window or _window(),
        total_files=3, total_commits=5, total_status_changes=1,
        total_comments=2, matters_touched=2,
        unattributed_commits=(), inactive_users=("Carol",),
        fetch_warning=None,
    )


def _ev(creator: str, file_type: str = "think") -> MatterEvent:
    return MatterEvent(
        matter_id="auth", matter_title="Auth Redesign",
        matter_current_status="executing",
        file=f"discussions/eng/auth/{creator}.md",
        file_type=file_type,
        created_at=datetime(2026, 4, 26, 12, tzinfo=CHINA_TZ),
        file_in_window=True, creator=creator, owner=creator,
        summary="x", status_change=None, verifications=(),
        comments_in_window=(),
    )


def _commit_for(pinyin: str) -> CommitRecord:
    return CommitRecord(
        sha="a"*40, author_name=pinyin, author_email=f"{pinyin}@x",
        committed_at=datetime(2026, 4, 26, 12, tzinfo=timezone.utc),
        subject="feat: x", files_changed=1, insertions=10, deletions=2,
        matched_pinyin=pinyin,
    )


def _activity_active(pinyin: str = "alice") -> UserActivity:
    return UserActivity(
        pinyin=pinyin, display_name=pinyin,
        file_creates=(_ev(pinyin),), file_owns=(),
        verifications_given=(), status_changes_triggered=(),
        comments_given=(), mentions_received=0,
        commits=(_commit_for(pinyin),),
    )


def _activity_inactive(pinyin: str = "carol") -> UserActivity:
    return UserActivity(
        pinyin=pinyin, display_name=pinyin,
        file_creates=(), file_owns=(),
        verifications_given=(), status_changes_triggered=(),
        comments_given=(), mentions_received=0, commits=(),
    )


def _settings(api_key: str = "k") -> AISettings:
    return AISettings(api_key=api_key, base_url="https://x", model="gpt-4")


# --------------------------------------------------------------------------- #
# fallback paths                                                              #
# --------------------------------------------------------------------------- #


def test_fallback_when_no_ai_flag():
    """--no-ai → status='fallback', reason mentions ai_disabled."""
    r = score_team(
        [_activity_active()], _summary(),
        ai_settings=_settings(), no_ai=True,
    )
    assert r.status == "fallback"
    assert "ai_disabled" in r.fallback_reason
    assert r.team_score == 3.0


def test_fallback_when_ai_settings_none():
    r = score_team([_activity_active()], _summary(), ai_settings=None)
    assert r.status == "fallback"
    assert "no api_key" in r.fallback_reason


def test_fallback_when_api_key_empty():
    r = score_team([_activity_active()], _summary(), ai_settings=_settings(""))
    assert r.status == "fallback"
    assert "no api_key" in r.fallback_reason


def test_fallback_when_api_key_whitespace():
    r = score_team([_activity_active()], _summary(), ai_settings=_settings("   "))
    assert r.status == "fallback"


def test_fallback_propagates_aierror(monkeypatch):
    """generate_text raises AIError → fallback with reason starting 'ai_error'."""
    def raising(**kwargs):
        raise AIError("upstream down")
    monkeypatch.setattr(score_module, "generate_text", raising)
    r = score_team([_activity_active()], _summary(), ai_settings=_settings())
    assert r.status == "fallback"
    assert "ai_error" in r.fallback_reason
    assert "upstream down" in r.fallback_reason


def test_fallback_propagates_timeout(monkeypatch):
    def raising(**kwargs):
        raise TimeoutError("too slow")
    monkeypatch.setattr(score_module, "generate_text", raising)
    r = score_team([_activity_active()], _summary(), ai_settings=_settings())
    assert r.status == "fallback"
    assert "TimeoutError" in r.fallback_reason


def test_fallback_when_ai_returns_non_json(monkeypatch):
    monkeypatch.setattr(score_module, "generate_text",
                        lambda **k: "this is just prose, not json at all")
    r = score_team([_activity_active()], _summary(), ai_settings=_settings())
    assert r.status == "fallback"
    assert "parse_error" in r.fallback_reason


def test_fallback_when_ai_returns_empty(monkeypatch):
    monkeypatch.setattr(score_module, "generate_text", lambda **k: "")
    r = score_team([_activity_active()], _summary(), ai_settings=_settings())
    assert r.status == "fallback"
    assert "parse_error" in r.fallback_reason


def test_fallback_when_team_score_out_of_range(monkeypatch):
    monkeypatch.setattr(score_module, "generate_text", lambda **k: json.dumps({
        "team": {
            "score": 9.0,   # out of [1.0, 5.0]
            "sub_scores": {"output": 5, "progress": 5, "blocker": 5, "collab": 5},
            "summary": "x",
        },
        "per_user": [],
    }))
    r = score_team([_activity_active()], _summary(), ai_settings=_settings())
    assert r.status == "fallback"
    assert "schema_error" in r.fallback_reason


def test_fallback_when_sub_score_missing(monkeypatch):
    """missing one of the 4 sub dimensions → schema_error."""
    monkeypatch.setattr(score_module, "generate_text", lambda **k: json.dumps({
        "team": {
            "score": 4.0,
            "sub_scores": {"output": 4, "progress": 4, "blocker": 4},  # missing collab
            "summary": "x",
        },
        "per_user": [],
    }))
    r = score_team([_activity_active()], _summary(), ai_settings=_settings())
    assert r.status == "fallback"
    assert "schema_error" in r.fallback_reason


def test_fallback_user_scores_bucketed_by_activity_count():
    """Fallback per-user scoring buckets (file+commits) → 2.5/3.5/4.5."""
    # Build users with 0 / 2 / 5 / 10 events respectively
    def with_n(p: str, n: int) -> UserActivity:
        return UserActivity(
            pinyin=p, display_name=p,
            file_creates=tuple(_ev(p) for _ in range(n)),
            file_owns=(), verifications_given=(),
            status_changes_triggered=(), comments_given=(),
            mentions_received=0, commits=(),
        )

    activities = [with_n("a", 2), with_n("b", 5), with_n("c", 10)]
    r = score_team(activities, _summary(), ai_settings=None)   # forces fallback
    by_pinyin = {u.pinyin: u for u in r.per_user}
    assert by_pinyin["a"].score == 2.5
    assert by_pinyin["b"].score == 3.5
    assert by_pinyin["c"].score == 4.5


def test_fallback_skips_inactive_users():
    """Inactive users (no activity at all) don't appear in per_user even
    in fallback mode."""
    r = score_team(
        [_activity_active("alice"), _activity_inactive("bob")],
        _summary(), ai_settings=None,
    )
    assert {u.pinyin for u in r.per_user} == {"alice"}


# --------------------------------------------------------------------------- #
# AI happy path                                                               #
# --------------------------------------------------------------------------- #


_GOOD_AI_RESPONSE = json.dumps({
    "team": {
        "score": 4.0,
        "sub_scores": {"output": 4.0, "progress": 3.5, "blocker": 4.5, "collab": 4.0},
        "summary": "全员有节奏",
    },
    "per_user": [
        {
            "pinyin": "alice",
            "score": 4.5,
            "sub_scores": {"output": 5.0, "progress": 4.0, "blocker": 5.0, "collab": 4.0},
            "summary": "完成 auth-redesign",
            "highlights": ["auth: finished", "verify ×2", "extra ignored"],
        },
    ],
}, ensure_ascii=False)


def test_ai_happy_path(monkeypatch):
    monkeypatch.setattr(score_module, "generate_text", lambda **k: _GOOD_AI_RESPONSE)
    r = score_team([_activity_active("alice")], _summary(),
                   ai_settings=_settings())
    assert r.status == "ai"
    assert r.team_score == 4.0
    assert r.team_sub_scores == {
        "output": 4.0, "progress": 3.5, "blocker": 4.5, "collab": 4.0
    }
    assert r.team_summary == "全员有节奏"
    assert len(r.per_user) == 1
    u = r.per_user[0]
    assert u.pinyin == "alice"
    assert u.score == 4.5
    assert u.summary == "完成 auth-redesign"
    # highlights truncated to first 3
    assert len(u.highlights) == 3


def test_ai_strips_markdown_fence(monkeypatch):
    """AI sometimes wraps JSON in ```json``` despite the prompt forbidding it.
    We strip and parse anyway rather than fall back over a cosmetic issue."""
    fenced = f"```json\n{_GOOD_AI_RESPONSE}\n```"
    monkeypatch.setattr(score_module, "generate_text", lambda **k: fenced)
    r = score_team([_activity_active("alice")], _summary(),
                   ai_settings=_settings())
    assert r.status == "ai"
    assert r.team_score == 4.0


def test_ai_strips_plain_fence_no_lang_tag(monkeypatch):
    """Some models use plain ``` without 'json'."""
    fenced = f"```\n{_GOOD_AI_RESPONSE}\n```"
    monkeypatch.setattr(score_module, "generate_text", lambda **k: fenced)
    r = score_team([_activity_active("alice")], _summary(),
                   ai_settings=_settings())
    assert r.status == "ai"


def test_ai_path_passes_compact_payload_to_generate_text(monkeypatch):
    """Verify the user-message JSON contains pre-aggregated UserActivity data,
    not raw timeline. Token-economy regression guard."""
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return _GOOD_AI_RESPONSE

    monkeypatch.setattr(score_module, "generate_text", fake_generate)

    score_team(
        [_activity_active("alice")], _summary(),
        ai_settings=_settings(),
    )
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert "Pivot 团队日报评分助手" in msgs[0]["content"]
    user_payload = json.loads(msgs[1]["content"])
    assert "team_stats" in user_payload
    assert user_payload["team_stats"]["files"] == 3
    assert "per_user" in user_payload
    # Activity count, not raw timeline
    assert user_payload["per_user"][0]["pinyin"] == "alice"
    assert "files_created" in user_payload["per_user"][0]
