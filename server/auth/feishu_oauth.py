from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import lark_oapi as lark

log = logging.getLogger(__name__)
from lark_oapi.api.authen.v1 import (
    CreateOidcAccessTokenRequest,
    CreateOidcAccessTokenRequestBody,
    GetUserInfoRequest,
)

AUTHORIZE_URL = "https://open.feishu.cn/open-apis/authen/v1/authorize"


@dataclass(frozen=True)
class TokenResult:
    access_token: str
    refresh_token: str | None
    expires_in: int | None


@dataclass(frozen=True)
class UserInfo:
    open_id: str
    union_id: str | None
    name: str
    avatar_url: str
    email: str | None


class FeishuOAuth:
    def __init__(self, app_id: str, app_secret: str, redirect_uri: str) -> None:
        self._app_id = app_id
        self._redirect_uri = redirect_uri
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .build()
        )

    def authorize_url(self, state: str) -> str:
        params = {
            "app_id": self._app_id,
            "redirect_uri": self._redirect_uri,
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenResult:
        req = (
            CreateOidcAccessTokenRequest.builder()
            .request_body(
                CreateOidcAccessTokenRequestBody.builder()
                .grant_type("authorization_code")
                .code(code)
                .build()
            )
            .build()
        )
        log.debug("oauth exchange_code start")
        resp = self._client.authen.v1.oidc_access_token.create(req)
        if not resp.success():
            log.warning("oauth exchange_code failed code=%s msg=%s", resp.code, resp.msg)
            raise FeishuOAuthError(resp.code, resp.msg)
        data = resp.data
        return TokenResult(
            access_token=data.access_token,
            refresh_token=getattr(data, "refresh_token", None),
            expires_in=getattr(data, "expires_in", None),
        )

    def get_user_info(self, user_access_token: str) -> UserInfo:
        req = GetUserInfoRequest.builder().build()
        opt = (
            lark.RequestOption.builder()
            .user_access_token(user_access_token)
            .build()
        )
        resp = self._client.authen.v1.user_info.get(req, opt)
        if not resp.success():
            log.warning("oauth get_user_info failed code=%s msg=%s", resp.code, resp.msg)
            raise FeishuOAuthError(resp.code, resp.msg)
        data = resp.data
        log.debug("oauth get_user_info open_id=%s name=%s", data.open_id, data.name)
        return UserInfo(
            open_id=data.open_id,
            union_id=getattr(data, "union_id", None),
            name=data.name,
            avatar_url=data.avatar_url,
            email=getattr(data, "email", None),
        )


class FeishuOAuthError(RuntimeError):
    def __init__(self, code: int, msg: str) -> None:
        super().__init__(f"feishu oauth error {code}: {msg}")
        self.code = code
        self.msg = msg
