"""Web Cookie 会话 + CSRF 双提交测试（ADR-4，与 Bearer JWT 共存）。

覆盖：
- web-login 成功下发 HttpOnly ff_session + 可读 csrftoken，响应体不含 token；
- web-login 失败沿用 401，不下发会话 cookie；
- cookie 认证下 GET 免 CSRF、POST/PUT 带正确 CSRF 成功、缺/错 CSRF 403 csrf_failed；
- Bearer 认证的写操作不需要 CSRF（native 不受影响）；
- web-logout 清除 cookie，之后受保护接口 401；
- GET /api/auth/csrf 下发可读 csrftoken；
- cookie 属性（HttpOnly/SameSite/Path/Secure 跟随环境）。
"""
from app.core.config import settings


def _parse_set_cookie_headers(response):
    """把响应里的多个 Set-Cookie 整理成 {name: header_value}。"""
    out = {}
    for raw in response.headers.get_list("set-cookie"):
        name = raw.split("=", 1)[0].strip()
        out[name] = raw
    return out


def _web_login(client, email="user@test.com", password="secret123"):
    """注册（走 native register 拿账号）再用 web-login 建立 cookie 会话，
    返回 (cookies_dict, set_cookie_dict, body)。"""
    client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "nickname": "Tester"},
    )
    resp = client.post(
        "/api/auth/web-login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.cookies, _parse_set_cookie_headers(resp), resp.json()


# ---------- web-login ----------
def test_web_login_sets_session_and_csrf_cookies(client):
    cookies, set_cookies, body = _web_login(client)

    # 响应体只含最小用户信息，不含 token 字符串
    assert set(body.keys()) >= {"id", "email"}
    assert "access_token" not in body
    assert body["email"] == "user@test.com"

    # 两个 cookie 都下发
    assert settings.web_cookie_name in set_cookies
    assert settings.csrf_cookie_name in set_cookies

    session = set_cookies[settings.web_cookie_name].lower()
    csrf = set_cookies[settings.csrf_cookie_name].lower()

    # ff_session 必须 HttpOnly；csrftoken 不得 HttpOnly（供 JS 读）
    assert "httponly" in session
    assert "httponly" not in csrf
    # SameSite=Lax，作用路径 /api
    assert "samesite=lax" in session
    assert "path=/api" in session
    assert "path=/api" in csrf


def test_web_login_failure_no_session_cookie(client):
    client.post(
        "/api/auth/register",
        json={"email": "user@test.com", "password": "secret123"},
    )
    resp = client.post(
        "/api/auth/web-login",
        json={"email": "user@test.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    set_cookies = _parse_set_cookie_headers(resp)
    assert settings.web_cookie_name not in set_cookies


def test_web_login_secure_flag_follows_environment(client):
    """开发环境默认 Secure=false；生产应为 true。"""
    _, set_cookies, _ = _web_login(client)
    session = set_cookies[settings.web_cookie_name].lower()
    if settings.is_production:
        assert "secure" in session
    else:
        assert "secure" not in session


# ---------- CSRF 端点 ----------
def test_csrf_endpoint_sets_readable_cookie(client):
    resp = client.get("/api/auth/csrf")
    assert resp.status_code == 200
    body = resp.json()
    assert "csrf" in body and body["csrf"]
    set_cookies = _parse_set_cookie_headers(resp)
    csrf = set_cookies[settings.csrf_cookie_name].lower()
    assert "httponly" not in csrf  # 前端 JS 必须可读


# ---------- cookie 认证读/写 ----------
def test_cookie_get_me_without_csrf_succeeds(client):
    _web_login(client)
    # TestClient 自动持有 cookie；GET 是安全方法，不需要 CSRF
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "user@test.com"


def test_cookie_write_with_correct_csrf_succeeds(client):
    cookies, _, _ = _web_login(client)
    csrf_token = cookies.get(settings.csrf_cookie_name)
    assert csrf_token
    resp = client.put(
        "/api/fitness/profile",
        json={"goal": "增肌", "height_cm": 175.0},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["goal"] == "增肌"


def test_cookie_write_missing_csrf_rejected(client):
    _web_login(client)
    resp = client.put(
        "/api/fitness/profile",
        json={"goal": "增肌"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "csrf_failed"


def test_cookie_write_wrong_csrf_rejected(client):
    _web_login(client)
    resp = client.put(
        "/api/fitness/profile",
        json={"goal": "增肌"},
        headers={"X-CSRF-Token": "not-the-real-token"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "csrf_failed"


def test_cookie_post_requires_csrf(client):
    """POST 写操作同样受 CSRF 保护（用一个无需额外依赖的认证 POST 做样例：
    /api/payment/orders 是 POST 且需登录；缺 CSRF 应在认证/业务前被 403）。"""
    _web_login(client)
    resp = client.post(
        "/api/payment/orders",
        json={"plan_code": "pro_monthly", "channel": "sandbox"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "csrf_failed"


def test_cookie_write_with_both_but_mismatched_csrf_rejected(client):
    """头与 cookie 都存在但不一致 -> 403（常量时间比较）。"""
    _web_login(client)
    resp = client.put(
        "/api/fitness/profile",
        json={"goal": "减脂"},
        headers={"X-CSRF-Token": "aaaa"},
        cookies={settings.csrf_cookie_name: "bbbb"},
    )
    assert resp.status_code == 403


# ---------- Bearer（native）不受影响 ----------
def test_bearer_write_does_not_require_csrf(client, register_user):
    """native 走 Authorization: Bearer，写操作不应被 CSRF 拦截。"""
    headers, _ = register_user()
    # 故意不带任何 CSRF 头/cookie
    resp = client.put(
        "/api/fitness/profile",
        json={"goal": "增肌", "height_cm": 175.0},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["goal"] == "增肌"


def test_bearer_login_still_returns_token(client):
    """现有 /api/auth/login 契约不变（native 用）。"""
    client.post(
        "/api/auth/register",
        json={"email": "user@test.com", "password": "secret123"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "user@test.com", "password": "secret123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    # native login 不应下发会话 cookie
    set_cookies = _parse_set_cookie_headers(resp)
    assert settings.web_cookie_name not in set_cookies


def test_bearer_takes_precedence_over_invalid_cookie(client, register_user):
    """Bearer 头存在时优先用它；即使携带无效 cookie 也不影响 native 请求。"""
    headers, _ = register_user()
    resp = client.get(
        "/api/auth/me",
        headers=headers,
        cookies={settings.web_cookie_name: "garbage"},
    )
    assert resp.status_code == 200


# ---------- logout ----------
def test_web_logout_clears_cookies_and_revokes_session(client):
    _, set_cookies, _ = _web_login(client)

    logout = client.post("/api/auth/web-logout")
    assert logout.status_code == 204
    cleared = _parse_set_cookie_headers(logout)
    # delete_cookie 会对两个名字都下发 Max-Age=0
    assert settings.web_cookie_name in cleared
    assert settings.csrf_cookie_name in cleared
    for header in cleared.values():
        assert "max-age=0" in header.lower()

    # TestClient 在 204 响应后会按 set-cookie 清掉 cookie；再访问受保护接口应 401
    me = client.get("/api/auth/me")
    assert me.status_code == 401


# ---------- 组合：web-login -> CSRF -> 写 -> logout ----------
def test_full_cookie_session_flow(client):
    # 1) 先拿 CSRF（模拟进入登录页）
    csrf_resp = client.get("/api/auth/csrf")
    assert csrf_resp.status_code == 200
    assert client.cookies.get(settings.csrf_cookie_name)

    # 2) web-login 建立会话并轮换 CSRF
    client.post(
        "/api/auth/register",
        json={"email": "u2@test.com", "password": "secret123"},
    )
    login = client.post(
        "/api/auth/web-login",
        json={"email": "u2@test.com", "password": "secret123"},
    )
    assert login.status_code == 200
    csrf_token = client.cookies.get(settings.csrf_cookie_name)
    assert client.cookies.get(settings.web_cookie_name)

    # 3) 带 CSRF 写成功
    ok = client.put(
        "/api/fitness/profile",
        json={"goal": "塑形"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert ok.status_code == 200

    # 4) 登出
    assert client.post("/api/auth/web-logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
