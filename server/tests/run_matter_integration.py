"""Matter API integration test driver — REAL HTTP edition.

Drives the Matter API against a running backend (default http://127.0.0.1:8000)
using a Bearer PAT. All writes go through the real ``write_session`` →
commit → push path, producing real git commits in the configured workspace.

Inputs (env vars):
- ``PIVOT_BASE_URL``          default ``http://127.0.0.1:8000``
- ``PIVOT_PAT``               required, ``pvt_...``
- ``TEST_MY_OPENID``          optional, used in the comment-with-mention case

Run:

    $env:PIVOT_PAT = "pvt_..."
    uv run python tests/integration/run_matter_integration.py

Outputs land in ``tests/test_output/matter-integration-test/`` (gitignored).
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "tests" / "test_output" / "matter-integration-test"
CASES_DIR = OUT_DIR / "cases"

BASE_URL = os.getenv("PIVOT_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PAT = os.getenv("PIVOT_PAT") or ""
TEST_MY_OPENID = os.getenv("TEST_MY_OPENID") or ""
RUN_TAG = time.strftime("%Y%m%d-%H%M%S")


def _ensure_out_dir() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CASES_DIR.mkdir(exist_ok=True)


def _client() -> httpx.Client:
    if not PAT:
        print("error: set PIVOT_PAT env var (pvt_...)", file=sys.stderr)
        sys.exit(2)
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {PAT}"},
        timeout=30.0,
    )


# ---------- helpers ----------


def _title(base: str) -> str:
    # Suffix run tag so matter slugs are unique across repeat runs.
    return f"{base}-{RUN_TAG}"


def _url_matter(matter_id: str, suffix: str = "") -> str:
    return f"/api/matters/{quote(matter_id, safe='')}{suffix}"


@dataclass
class Step:
    name: str
    method: str
    path: str
    body: dict | None = None
    expect_status: int = 200


class CaseRunner:
    def __init__(self, case_id: str, client: httpx.Client):
        self.case_id = case_id
        self.client = client
        self.dir = CASES_DIR / case_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.step_idx = 0
        self.failures: list[str] = []

    def _record(self, step: Step, response: httpx.Response) -> dict:
        self.step_idx += 1
        stem = f"{self.step_idx:02d}-{step.name}"
        if step.body is not None:
            (self.dir / f"{stem}.in.json").write_text(
                json.dumps(
                    {"method": step.method, "path": step.path, "body": step.body},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        try:
            body = response.json()
        except Exception:
            body = {"_raw": response.text}
        (self.dir / f"{stem}.out.json").write_text(
            json.dumps(
                {"status": response.status_code, "body": body},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        if response.status_code != step.expect_status:
            self.failures.append(
                f"[{self.case_id}] step {self.step_idx} {step.name}: "
                f"expected HTTP {step.expect_status}, got {response.status_code}; "
                f"body={body!r}"
            )
        return body

    def do(self, step: Step) -> dict:
        method = step.method.upper()
        if method == "GET":
            resp = self.client.get(step.path)
        elif method == "POST":
            resp = self.client.post(step.path, json=step.body or {})
        else:
            raise ValueError(method)
        return self._record(step, resp)

    def save_final_index(self, matter_id: str, workspace_path: Path) -> dict:
        # Try disk directly (workspace_path known); also request /api/matters/{id} to confirm.
        index_path = workspace_path / "index" / f"{matter_id}.index.yaml"
        if index_path.is_file():
            (self.dir / "final-index.yaml").write_text(
                index_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            return yaml.safe_load(index_path.read_text(encoding="utf-8"))
        return {}

    def expect(self, condition: bool, msg: str) -> None:
        if not condition:
            self.failures.append(f"[{self.case_id}] assertion failed: {msg}")


# ---------- cases ----------


def case_a1_pause_from_planning(client, workspace_path) -> list[str]:
    r = CaseRunner("A1-pause-from-planning", client)
    title = _title("IntegTest-A1-PauseFromPlanning")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {
            "type": "think",
            "summary": "初步构想",
            "body": "# Summary\n\n初步构想。\n",
        },
    }))
    matter_id = created["matter_id"]
    first_file = created["file"]

    r.do(Step("pause-via-think", "POST", _url_matter(matter_id, "/files"), body={
        "type": "think",
        "summary": "暂停：等第三方确认",
        "body": "# Summary\n\n等依赖方确认再继续。\n",
        "quote": first_file,
        "status_change": {"from": "planning", "to": "paused"},
    }))

    detail = r.do(Step("get-detail", "GET", _url_matter(matter_id)))
    idx = r.save_final_index(matter_id, workspace_path)

    r.expect(idx.get("matter", {}).get("current_status") == "paused",
             "current_status should be paused")
    r.expect(len(idx.get("timeline", [])) == 2, "timeline should have 2 items")
    r.expect(idx["timeline"][1].get("status_change", {}).get("to") == "paused",
             "2nd item should carry status_change to paused")
    r.expect(detail["matter"]["current_status"] == "paused",
             "detail API should reflect paused")
    return r.failures


def case_a2_loop_round_trip(client, workspace_path) -> list[str]:
    r = CaseRunner("A2-loop-a-planning-paused-planning", client)
    title = _title("IntegTest-A2-RoundTrip")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    }))
    matter_id = created["matter_id"]
    r.do(Step("pause", "POST", _url_matter(matter_id, "/files"), body={
        "type": "think", "summary": "pause", "body": "",
        "status_change": {"from": "planning", "to": "paused"},
    }))
    r.do(Step("resume-to-planning", "POST", _url_matter(matter_id, "/files"), body={
        "type": "think", "summary": "resume", "body": "",
        "status_change": {"from": "paused", "to": "planning"},
    }))
    idx = r.save_final_index(matter_id, workspace_path)
    r.expect(idx["matter"]["current_status"] == "planning",
             "current_status should be planning after resume")
    r.expect(len(idx["timeline"]) == 3, "timeline should have 3 items")
    return r.failures


def case_a3_paused_to_executing(client, workspace_path) -> list[str]:
    """Loop A alt: paused → executing via think, then an act concretely starts work.

    Product doc §九.1 requires executing to be carried by at least one act;
    resuming via think alone leaves executing semantically empty, so we follow
    with a real act to close the loop.
    """
    r = CaseRunner("A3-paused-to-executing-with-act", client)
    title = _title("IntegTest-A3-ResumeExecuting")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "think", "summary": "初步方案", "body": "# Summary\n\n初步方案\n"},
    }))
    matter_id = created["matter_id"]
    first_file = created["file"]

    r.do(Step("pause", "POST", _url_matter(matter_id, "/files"), body={
        "type": "think",
        "summary": "暂停：等第三方确认",
        "body": "# Summary\n\n等依赖\n",
        "quote": first_file,
        "status_change": {"from": "planning", "to": "paused"},
    }))
    resume = r.do(Step("resume-to-executing", "POST", _url_matter(matter_id, "/files"), body={
        "type": "think",
        "summary": "外部就绪，恢复到 executing",
        "body": "# Summary\n\n恢复原因：依赖已 ready\n",
        "status_change": {"from": "paused", "to": "executing"},
    }))
    resume_file = resume["item"]["file"]

    r.do(Step("first-act-after-resume", "POST", _url_matter(matter_id, "/files"), body={
        "type": "act",
        "summary": "落地第一个行动",
        "body": "# What To Do\n\n- 对齐接口\n- 写服务端实现\n",
        "quote": resume_file,
    }))

    idx = r.save_final_index(matter_id, workspace_path)
    r.expect(idx["matter"]["current_status"] == "executing",
             "current_status should be executing")
    r.expect(len(idx["timeline"]) == 4, "timeline should have 4 items (think+think+think+act)")
    last = idx["timeline"][-1]
    r.expect(last["type"] == "act" and last["quote"] == resume_file,
             "last item should be act quoting the resume-think")
    return r.failures


def case_b1_loop_b_finished(client, workspace_path) -> list[str]:
    r = CaseRunner("B1-loop-b-finished-reviewed", client)
    title = _title("IntegTest-B1-AuthRedesign")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {
            "type": "think",
            "summary": "梳理登录链路",
            "body": "# Summary\n\n梳理登录链路。\n",
        },
    }))
    matter_id = created["matter_id"]
    think_file = created["file"]

    act_resp = r.do(Step("act-enter-executing", "POST", _url_matter(matter_id, "/files"), body={
        "type": "act",
        "owner": "liuyu",
        "summary": "按修正后的链路实现",
        "body": "# What To Do\n\n- 调整登录回跳\n- cookie 持久化\n",
        "quote": think_file,
        "status_change": {"from": "planning", "to": "executing"},
    }))
    act_file = act_resp["item"]["file"]

    r.do(Step("verify-pass", "POST", _url_matter(matter_id, "/files"), body={
        "type": "verify",
        "summary": "主链路通过",
        "body": "# Verifications\n",
        "quote": act_file,
        "verifications": [
            {"target": act_file, "judgement": "passed", "comment": "可接受"},
        ],
    }))

    r.do(Step("result-finished", "POST", _url_matter(matter_id, "/result"), body={
        "summary": "事项完成",
        "body": "整体结果可接受。",
        "outcome": "finished",
    }))

    r.do(Step("insight-to-reviewed", "POST", _url_matter(matter_id, "/files"), body={
        "type": "insight",
        "summary": "需求澄清节奏待优化",
        "body": "# Summary\n\n沉淀复盘。\n",
        "status_change": {"from": "finished", "to": "reviewed"},
    }))

    detail = r.do(Step("get-detail", "GET", _url_matter(matter_id)))
    idx = r.save_final_index(matter_id, workspace_path)

    r.expect(idx["matter"]["current_status"] == "reviewed",
             "final status should be reviewed")
    r.expect(len(idx["timeline"]) == 5, "timeline should have 5 items")
    types_seq = [it["type"] for it in idx["timeline"]]
    r.expect(types_seq == ["think", "act", "verify", "result", "insight"],
             f"type sequence mismatch: {types_seq}")
    result_item = next(it for it in idx["timeline"] if it["type"] == "result")
    r.expect(result_item.get("outcome") == "finished",
             "result.outcome should be finished")
    act_item = next(it for it in idx["timeline"] if it["type"] == "act")
    r.expect(act_item["owner"] == "liuyu", "act.owner should be liuyu")
    r.expect(detail["matter"]["current_status"] == "reviewed",
             "detail API reflects reviewed")
    return r.failures


def case_b2_cancelled_reviewed(client, workspace_path) -> list[str]:
    r = CaseRunner("B2-cancelled-reviewed", client)
    title = _title("IntegTest-B2-CancelPath")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "think", "summary": "x", "body": ""},
    }))
    matter_id = created["matter_id"]
    r.do(Step("act-enter-executing", "POST", _url_matter(matter_id, "/files"), body={
        "type": "act", "summary": "work",
        "status_change": {"from": "planning", "to": "executing"},
    }))
    r.do(Step("result-cancel", "POST", _url_matter(matter_id, "/result"), body={
        "summary": "取消",
        "outcome": "cancelled",
    }))
    r.do(Step("insight-review", "POST", _url_matter(matter_id, "/files"), body={
        "type": "insight", "summary": "为什么取消",
        "status_change": {"from": "cancelled", "to": "reviewed"},
    }))
    idx = r.save_final_index(matter_id, workspace_path)
    r.expect(idx["matter"]["current_status"] == "reviewed",
             "status should end reviewed")
    result_item = next(it for it in idx["timeline"] if it["type"] == "result")
    r.expect(result_item["outcome"] == "cancelled",
             "outcome should be cancelled")
    return r.failures


def case_n1_reject_result_in_planning(client, workspace_path) -> list[str]:
    r = CaseRunner("N1-reject-result-in-planning", client)
    title = _title("IntegTest-N1-RejectResult")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    }))
    matter_id = created["matter_id"]
    bad = r.do(Step(
        "try-result-in-planning", "POST", _url_matter(matter_id, "/files"),
        body={"type": "result", "summary": "nope", "outcome": "finished",
              "status_change": {"from": "planning", "to": "finished"}},
        expect_status=422,
    ))
    r.expect(bad["detail"]["code"] == "type_not_allowed",
             f"expected type_not_allowed, got {bad['detail'].get('code')}")
    r.save_final_index(matter_id, workspace_path)
    return r.failures


def case_n2_reject_post_reviewed(client, workspace_path) -> list[str]:
    r = CaseRunner("N2-reject-post-reviewed", client)
    title = _title("IntegTest-N2-StrictReviewed")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "act", "summary": "s", "body": ""},
    }))
    matter_id = created["matter_id"]
    r.do(Step("to-executing", "POST", _url_matter(matter_id, "/files"), body={
        "type": "act", "summary": "a",
        "status_change": {"from": "planning", "to": "executing"},
    }))
    r.do(Step("finish", "POST", _url_matter(matter_id, "/result"), body={
        "summary": "done", "outcome": "finished",
    }))
    r.do(Step("review", "POST", _url_matter(matter_id, "/files"), body={
        "type": "insight", "summary": "lesson",
        "status_change": {"from": "finished", "to": "reviewed"},
    }))
    bad = r.do(Step(
        "try-insight-after-reviewed", "POST", _url_matter(matter_id, "/files"),
        body={"type": "insight", "summary": "oops"},
        expect_status=422,
    ))
    r.expect(bad["detail"]["code"] == "type_not_allowed",
             "reviewed must strictly deny new files")
    r.save_final_index(matter_id, workspace_path)
    return r.failures


def case_n3_verify_target_not_act(client, workspace_path) -> list[str]:
    r = CaseRunner("N3-verify-target-not-act", client)
    title = _title("IntegTest-N3-TargetNotAct")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    }))
    matter_id = created["matter_id"]
    think_file = created["file"]
    bad = r.do(Step(
        "verify-against-think", "POST", _url_matter(matter_id, "/files"),
        body={"type": "verify", "summary": "bad target",
              "verifications": [{"target": think_file, "judgement": "passed", "comment": ""}]},
        expect_status=422,
    ))
    r.expect(bad["detail"]["code"] == "verification_target_not_act",
             f"expected verification_target_not_act, got {bad['detail'].get('code')}")
    r.save_final_index(matter_id, workspace_path)
    return r.failures


def case_n4_verify_target_not_found(client, workspace_path) -> list[str]:
    r = CaseRunner("N4-verify-target-not-found", client)
    title = _title("IntegTest-N4-TargetNotFound")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    }))
    matter_id = created["matter_id"]
    bad = r.do(Step(
        "verify-missing-target", "POST", _url_matter(matter_id, "/files"),
        body={"type": "verify", "summary": "missing",
              "verifications": [{"target": "discussions/ghost/999_nobody.md",
                                 "judgement": "passed", "comment": ""}]},
        expect_status=422,
    ))
    r.expect(bad["detail"]["code"] == "verification_target_not_found",
             f"expected verification_target_not_found, got {bad['detail'].get('code')}")
    r.save_final_index(matter_id, workspace_path)
    return r.failures


def case_n5_verify_via_refer_ok(client, workspace_path) -> list[str]:
    r = CaseRunner("N5-verify-via-refer-ok", client)
    title = _title("IntegTest-N5-ReferWhitelist")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "think", "summary": "s", "body": ""},
    }))
    matter_id = created["matter_id"]
    external = "discussions/external-matter/001_u_act_x.md"
    r.do(Step(
        "verify-via-refer", "POST", _url_matter(matter_id, "/files"),
        body={"type": "verify", "summary": "cross-matter",
              "refer": [external],
              "verifications": [{"target": external, "judgement": "passed", "comment": "ok"}]},
    ))
    idx = r.save_final_index(matter_id, workspace_path)
    verify_item = next(it for it in idx["timeline"] if it["type"] == "verify")
    r.expect(verify_item["verifications"][0]["target"] == external,
             "cross-matter target preserved via refer whitelist")
    return r.failures


def case_d1_multi_round_discussion(client, workspace_path) -> list[str]:
    """Multiple think files continuing via quote chain (discussion-style depth).

    Each new think quotes the previous, forming a lineage:
      t1 → t2 (quote=t1) → t3 (quote=t2) → t4 (quote=t3)
    """
    r = CaseRunner("D1-multi-round-think-chain", client)
    title = _title("IntegTest-D1-DiscussionChain")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {
            "type": "think",
            "summary": "#1 把问题摆清楚",
            "body": "# Summary\n\n目前登录链路在飞书内打开有两条不一致的回跳路径。\n",
        },
    }))
    matter_id = created["matter_id"]
    prev = created["file"]

    bodies = [
        ("#2 分析候选方案",
         "# Summary\n\n方案 A：走飞书 authz code 预换。方案 B：浏览器 OAuth 统一。\n"),
        ("#3 倾向方案 B",
         "# Summary\n\n方案 B 实现复杂度低，回跳一致性强，但需要兼容飞书端内打开。\n"),
        ("#4 确认 quote/refer 模型",
         "# Summary\n\n方案 B 的 open_id 如何在 session 内保留？需要在下一篇 act 里落实。\n"),
    ]
    for i, (summary, body) in enumerate(bodies, start=2):
        resp = r.do(Step(
            f"think-{i}", "POST", _url_matter(matter_id, "/files"),
            body={"type": "think", "summary": summary, "body": body, "quote": prev},
        ))
        prev = resp["item"]["file"]

    idx = r.save_final_index(matter_id, workspace_path)
    r.expect(len(idx["timeline"]) == 4, "4-item think chain")
    # quote lineage check
    timeline = idx["timeline"]
    r.expect(timeline[0].get("quote") in (None, ""),
             "first item has no quote")
    for i in range(1, 4):
        r.expect(timeline[i]["quote"] == timeline[i - 1]["file"],
                 f"item {i+1} must quote item {i}")
    r.expect(idx["matter"]["current_status"] == "planning",
             "status stays planning (no status_change triggered)")
    return r.failures


def case_d2_executing_depth_multiple_acts(client, workspace_path) -> list[str]:
    """Executing with multiple acts + mid-course think + a verify that covers two acts.

    Shape:
      think1(initial) → act1(→executing) → think2(mid-course修正) → act2(parallel)
      → verify(covers act1 & act2) → result(finished)
    """
    r = CaseRunner("D2-executing-depth-multiple-acts", client)
    title = _title("IntegTest-D2-ParallelActs")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {
            "type": "think",
            "summary": "拆子任务",
            "body": "# Summary\n\n拆成两个并行子任务\n",
        },
    }))
    matter_id = created["matter_id"]
    think1 = created["file"]

    act1_resp = r.do(Step("act1-enter-executing", "POST", _url_matter(matter_id, "/files"), body={
        "type": "act",
        "owner": "liuyu",
        "summary": "子任务 A：回跳链路",
        "body": "# What To Do\n\n回跳链路\n",
        "quote": think1,
        "status_change": {"from": "planning", "to": "executing"},
    }))
    act1 = act1_resp["item"]["file"]

    think2_resp = r.do(Step("think2-mid-course", "POST", _url_matter(matter_id, "/files"), body={
        "type": "think",
        "summary": "修正理解：子任务 B 先做不阻塞 A",
        "body": "# Summary\n\n调整顺序\n",
        "quote": act1,
    }))
    think2 = think2_resp["item"]["file"]

    act2_resp = r.do(Step("act2-parallel", "POST", _url_matter(matter_id, "/files"), body={
        "type": "act",
        "owner": "dengke",
        "summary": "子任务 B：cookie 持久化",
        "body": "# What To Do\n\ncookie 持久化\n",
        "quote": think2,
    }))
    act2 = act2_resp["item"]["file"]

    r.do(Step("verify-covers-both-acts", "POST", _url_matter(matter_id, "/files"), body={
        "type": "verify",
        "summary": "两条行动汇总判断",
        "body": "# Verifications\n",
        "quote": act2,
        "verifications": [
            {"target": act1, "judgement": "passed",
             "comment": "主链路通过，质量可接受"},
            {"target": act2, "judgement": "failed",
             "comment": "cookie 跨域场景未覆盖，需返工"},
        ],
    }))

    r.do(Step("result-finished", "POST", _url_matter(matter_id, "/result"), body={
        "summary": "整体结果可接受，cookie 跨域问题转到后续复盘",
        "outcome": "finished",
    }))

    idx = r.save_final_index(matter_id, workspace_path)
    r.expect(len(idx["timeline"]) == 6, f"6 items expected, got {len(idx['timeline'])}")
    types_seq = [it["type"] for it in idx["timeline"]]
    r.expect(types_seq == ["think", "act", "think", "act", "verify", "result"],
             f"type sequence wrong: {types_seq}")
    act_items = [it for it in idx["timeline"] if it["type"] == "act"]
    owners = {it["owner"] for it in act_items}
    r.expect(owners == {"liuyu", "dengke"},
             f"two different act owners expected, got {owners}")
    verify_item = next(it for it in idx["timeline"] if it["type"] == "verify")
    r.expect(len(verify_item["verifications"]) == 2,
             "verify should cover 2 acts")
    judgements = {v["judgement"] for v in verify_item["verifications"]}
    r.expect(judgements == {"passed", "failed"},
             f"mixed judgements expected, got {judgements}")
    r.expect(idx["matter"]["current_status"] == "finished",
             "status should be finished")
    return r.failures


def case_d3_cross_matter_refer(client, workspace_path) -> list[str]:
    """Build matter X, then matter Y whose act refers (refer) to a file in X."""
    r = CaseRunner("D3-cross-matter-refer", client)

    # Matter X: create + push an act so we have a concrete file to refer to.
    tx = _title("IntegTest-D3-Source")
    createdX = r.do(Step("create-source-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": tx,
        "initial_file": {
            "type": "think",
            "summary": "源 matter 想法",
            "body": "# Summary\n\n这篇要被 matter Y refer\n",
        },
    }))
    matter_x = createdX["matter_id"]
    x_think = createdX["file"]
    actX_resp = r.do(Step("source-act", "POST", _url_matter(matter_x, "/files"), body={
        "type": "act",
        "summary": "源 matter 的行动",
        "body": "# What To Do\n\nY 要引用这篇\n",
        "quote": x_think,
        "status_change": {"from": "planning", "to": "executing"},
    }))
    x_act = actX_resp["item"]["file"]

    # Matter Y: act in a new matter that refer's back into matter X.
    ty = _title("IntegTest-D3-Consumer")
    createdY = r.do(Step("create-consumer-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": ty,
        "initial_file": {
            "type": "think",
            "summary": "基于 X 的延伸讨论",
            "body": "# Summary\n\n参考 X 的行动\n",
        },
    }))
    matter_y = createdY["matter_id"]

    y_act = r.do(Step("consumer-act-with-refer", "POST", _url_matter(matter_y, "/files"), body={
        "type": "act",
        "summary": "在 Y 里延续 X 的行动",
        "body": "# What To Do\n\n延续 X.act\n",
        "quote": createdY["file"],
        "refer": [x_act, x_think],
        "status_change": {"from": "planning", "to": "executing"},
    }))

    # Verify in Y pointing at X.act via refer whitelist.
    r.do(Step("consumer-verify-refer-whitelist", "POST", _url_matter(matter_y, "/files"), body={
        "type": "verify",
        "summary": "针对 X.act 做跨 matter 验证",
        "body": "# Verifications\n",
        "refer": [x_act],
        "verifications": [
            {"target": x_act, "judgement": "passed",
             "comment": "X 的行动对 Y 的前置已满足"},
        ],
    }))

    idx_y = r.save_final_index(matter_y, workspace_path)
    act_in_y = next(it for it in idx_y["timeline"] if it["type"] == "act")
    r.expect(x_act in (act_in_y.get("refer") or []),
             f"Y's act should refer to X.act; got refer={act_in_y.get('refer')}")
    verify_in_y = next(it for it in idx_y["timeline"] if it["type"] == "verify")
    r.expect(verify_in_y["verifications"][0]["target"] == x_act,
             "Y's verify.target should be X.act")
    r.expect(idx_y["matter"]["current_status"] == "executing",
             "Y should be executing (triggered by its act)")
    return r.failures


def case_c1_comment_with_mention(client, workspace_path) -> list[str]:
    """Exercise /comments endpoint + mention, using TEST_MY_OPENID as the @target."""
    r = CaseRunner("C1-comment-with-mention", client)
    title = _title("IntegTest-C1-CommentMention")
    created = r.do(Step("create-matter", "POST", "/api/matters", body={
        "category": "IntegTest",
        "title": title,
        "initial_file": {"type": "think", "summary": "s", "body": "首帖"},
    }))
    matter_id = created["matter_id"]
    target_file = created["file"]

    body = {"target_file": target_file, "body": "请你确认一下这个方向"}
    if TEST_MY_OPENID:
        body["mentions"] = [TEST_MY_OPENID]
    r.do(Step("append-comment", "POST", _url_matter(matter_id, "/comments"), body=body))

    idx = r.save_final_index(matter_id, workspace_path)
    comments = idx["timeline"][0].get("comments") or []
    r.expect(len(comments) == 1, "one comment on first item")
    if TEST_MY_OPENID:
        r.expect(comments[0].get("mentions") == [TEST_MY_OPENID],
                 "mention open_id preserved")
    # matter.updated_at must NOT advance past created_at (comments don't bump progress).
    r.expect(idx["matter"]["updated_at"] == idx["matter"]["created_at"],
             "comment should not bump matter.updated_at")
    return r.failures


# ---------- driver ----------


def _fetch_workspace_path(client: httpx.Client) -> Path:
    resp = client.get("/api/workspace/status")
    resp.raise_for_status()
    path = resp.json()["path"]
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _check_md_index_state(workspace_path: Path) -> list[str]:
    """Scan every MD under discussions/IntegTest/*<RUN_TAG>*/ and confirm
    frontmatter carries `index_state: indexed`. Anything else means either
    (a) the two-phase write did not complete, or (b) the frontmatter dropped
    the flag (schema regression)."""
    import yaml as _yaml
    failures: list[str] = []
    root = workspace_path / "discussions" / "IntegTest"
    if not root.is_dir():
        return failures
    for matter_dir in root.iterdir():
        if not matter_dir.is_dir():
            continue
        if RUN_TAG not in matter_dir.name:
            continue
        for md in matter_dir.glob("*.md"):
            text = md.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                failures.append(f"md without frontmatter: {md}")
                continue
            try:
                fm_text = text.split("---\n", 2)[1]
                fm = _yaml.safe_load(fm_text) or {}
            except Exception as e:
                failures.append(f"md frontmatter unparseable: {md}: {e}")
                continue
            state = fm.get("index_state")
            if state != "indexed":
                failures.append(
                    f"md index_state != 'indexed' (got {state!r}): {md}"
                )
    return failures


def main() -> int:
    _ensure_out_dir()
    client = _client()
    workspace_path = _fetch_workspace_path(client)
    print(f"backend: {BASE_URL}")
    print(f"workspace: {workspace_path}")
    print(f"run tag: {RUN_TAG}")
    print()

    cases = [
        case_a1_pause_from_planning,
        case_a2_loop_round_trip,
        case_a3_paused_to_executing,
        case_b1_loop_b_finished,
        case_b2_cancelled_reviewed,
        case_n1_reject_result_in_planning,
        case_n2_reject_post_reviewed,
        case_n3_verify_target_not_act,
        case_n4_verify_target_not_found,
        case_n5_verify_via_refer_ok,
        case_c1_comment_with_mention,
        case_d1_multi_round_discussion,
        case_d2_executing_depth_multiple_acts,
        case_d3_cross_matter_refer,
    ]

    summary: list[str] = []
    all_failures: list[str] = []
    for case in cases:
        try:
            fails = case(client, workspace_path)
        except Exception as e:
            fails = [f"[{case.__name__}] exception: {e!r}"]
        all_failures.extend(fails)
        summary.append(f"  [{('FAIL' if fails else 'PASS'):>4}] {case.__name__}")

    # Sweep: every MD produced during this run must be index_state=indexed.
    # Any un-indexed file points at a partially-written pair (MD landed but
    # INDEX update failed) — serious data safety red flag.
    index_state_failures = _check_md_index_state(workspace_path)
    if index_state_failures:
        all_failures.extend(index_state_failures)
        summary.append(f"  [FAIL] md_index_state_sweep")
    else:
        summary.append(f"  [PASS] md_index_state_sweep")

    report_lines = [
        "# Matter Integration Test Report (real backend)",
        "",
        f"Backend: {BASE_URL}",
        f"Workspace: {workspace_path}",
        f"Run tag: {RUN_TAG}",
        "",
        f"Cases run: {len(cases)}",
        f"Failures : {len(all_failures)}",
        "",
        "## Results",
        "",
        *summary,
        "",
        "## Failures",
        "",
        *([f"- {msg}" for msg in all_failures] if all_failures else ["(none)"]),
    ]
    (OUT_DIR / "REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")

    print("\n".join(report_lines))
    return 1 if all_failures else 0


if __name__ == "__main__":
    sys.exit(main())
