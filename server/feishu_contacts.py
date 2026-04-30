from __future__ import annotations

import logging
from typing import Callable

import httpx

from server.contacts import ContactRepo

log = logging.getLogger(__name__)

_SCOPES_URL = "https://open.feishu.cn/open-apis/contact/v3/scopes"
_FIND_BY_DEPT_URL = "https://open.feishu.cn/open-apis/contact/v3/users/find_by_department"
_CHILDREN_URL_TEMPLATE = (
    "https://open.feishu.cn/open-apis/contact/v3/departments/{dept_id}/children"
)
_GET_USER_URL_TEMPLATE = "https://open.feishu.cn/open-apis/contact/v3/users/{user_id}"
_TIMEOUT = 30.0


class FeishuContactSyncer:
    def __init__(
        self,
        *,
        contacts: ContactRepo,
        tenant_token_getter: Callable[[], str],
    ) -> None:
        self._contacts = contacts
        self._get_tenant_token = tenant_token_getter

    def sync(self) -> int:
        """Pull the company directory using the tenant_access_token (the
        Feishu app's own credentials, server-level), no per-user OAuth
        token required. This means an invite-only admin (no Feishu
        binding) can run /api/contacts/sync as long as the app has
        ``contact:user.base:readonly`` permissions wired in the Feishu
        admin console."""
        tenant_token = self._get_tenant_token()
        dept_ids, user_ids_from_scope = self._fetch_scopes(tenant_token)
        log.info(
            "feishu scopes departments=%d users=%d",
            len(dept_ids), len(user_ids_from_scope),
        )
        if not dept_ids and not user_ids_from_scope:
            log.warning(
                "feishu scope empty; check that the app has contact permissions"
                " and its visibility range includes real members"
            )
            return 0

        all_user_ids: set[str] = set(user_ids_from_scope)
        seen_depts: set[str] = set()
        queue: list[str] = list(dept_ids)
        while queue:
            d = queue.pop(0)
            if d in seen_depts:
                continue
            seen_depts.add(d)
            for u in self._list_users_in_dept(tenant_token, d):
                oid = u.get("open_id")
                if oid:
                    all_user_ids.add(oid)
            for child in self._list_children(tenant_token, d):
                if child not in seen_depts:
                    queue.append(child)

        users_by_oid: dict[str, dict] = {}
        for uid in all_user_ids:
            u = self._get_user(tenant_token, uid)
            if u and u.get("open_id"):
                users_by_oid[u["open_id"]] = u

        batch = [
            {
                "open_id": u["open_id"],
                "union_id": u.get("union_id"),
                "name": u.get("name", ""),
                "en_name": u.get("en_name"),
                "avatar_url": (u.get("avatar") or {}).get("avatar_240", ""),
            }
            for u in users_by_oid.values()
        ]
        self._contacts.upsert_many(batch)
        log.info(
            "contact sync done users=%d (discovered_ids=%d, departments=%d)",
            len(users_by_oid), len(all_user_ids), len(seen_depts),
        )
        return len(users_by_oid)

    def _fetch_scopes(self, token: str) -> tuple[list[str], list[str]]:
        depts: list[str] = []
        users: list[str] = []
        page_token = ""
        while True:
            params: dict[str, object] = {
                "page_size": 50,
                "department_id_type": "open_department_id",
                "user_id_type": "open_id",
            }
            if page_token:
                params["page_token"] = page_token
            resp = httpx.get(
                _SCOPES_URL, params=params,
                headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT,
            )
            try:
                data = resp.json()
            except Exception:
                log.warning("scopes invalid JSON status=%d", resp.status_code)
                return depts, users
            if data.get("code") != 0:
                log.warning("scopes error code=%s msg=%s", data.get("code"), data.get("msg"))
                return depts, users
            d = data.get("data") or {}
            depts.extend(d.get("department_ids") or [])
            users.extend(d.get("user_ids") or [])
            if not d.get("has_more"):
                break
            page_token = d.get("page_token", "")
            if not page_token:
                break
        return depts, users

    def _list_users_in_dept(self, token: str, dept_id: str) -> list[dict]:
        out: list[dict] = []
        page_token = ""
        while True:
            params: dict[str, object] = {
                "department_id": dept_id,
                "department_id_type": "open_department_id",
                "user_id_type": "open_id",
                "page_size": 100,
            }
            if page_token:
                params["page_token"] = page_token
            try:
                resp = httpx.get(
                    _FIND_BY_DEPT_URL, params=params,
                    headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT,
                )
                data = resp.json()
            except Exception:
                log.warning("users_in_dept failed dept=%s", dept_id, exc_info=True)
                return out
            if data.get("code") != 0:
                log.warning(
                    "users_in_dept error dept=%s code=%s msg=%s",
                    dept_id, data.get("code"), data.get("msg"),
                )
                return out
            items = (data.get("data") or {}).get("items") or []
            if items and not out:
                log.debug(
                    "find_by_department sample keys=%s",
                    list(items[0].keys()),
                )
            out.extend(items)
            if not (data.get("data") or {}).get("has_more"):
                break
            page_token = (data.get("data") or {}).get("page_token", "")
            if not page_token:
                break
        return out

    def _list_children(self, token: str, parent_id: str) -> list[str]:
        ids: list[str] = []
        page_token = ""
        url = _CHILDREN_URL_TEMPLATE.format(dept_id=parent_id)
        while True:
            params: dict[str, object] = {
                "department_id_type": "open_department_id",
                "page_size": 50,
            }
            if page_token:
                params["page_token"] = page_token
            try:
                resp = httpx.get(
                    url, params=params,
                    headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT,
                )
                data = resp.json()
            except Exception:
                log.warning("list_children failed parent=%s", parent_id, exc_info=True)
                return ids
            if data.get("code") != 0:
                log.debug(
                    "list_children error parent=%s code=%s msg=%s",
                    parent_id, data.get("code"), data.get("msg"),
                )
                return ids
            for item in (data.get("data") or {}).get("items") or []:
                did = item.get("open_department_id") or item.get("department_id")
                if did:
                    ids.append(did)
            if not (data.get("data") or {}).get("has_more"):
                break
            page_token = (data.get("data") or {}).get("page_token", "")
            if not page_token:
                break
        return ids

    def _get_user(self, token: str, user_id: str) -> dict | None:
        url = _GET_USER_URL_TEMPLATE.format(user_id=user_id)
        try:
            resp = httpx.get(
                url,
                params={"user_id_type": "open_id", "department_id_type": "open_department_id"},
                headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT,
            )
            data = resp.json()
        except Exception:
            log.warning("get_user failed uid=%s", user_id, exc_info=True)
            return None
        if data.get("code") != 0:
            log.warning("get_user error uid=%s code=%s msg=%s",
                        user_id, data.get("code"), data.get("msg"))
            return None
        user = (data.get("data") or {}).get("user")
        if user:
            log.debug(
                "get_user sample uid=%s keys=%s", user_id, list(user.keys()),
            )
        return user
