"""介绍作品页（落地页 /）冒烟测试。

- GET / 返回 200 HTML，包含关键区块与品牌主色。
- 未配置下载链接时，不渲染真实下载外链，按钮显示「即将开放」。
- 配置了下载链接时，渲染为真实 <a href>。
- 接口发现信息迁移到 GET /api，根路径不再返回 JSON。
"""
from app.core.config import settings


LANDING_SECTIONS = [
    "FormFit",
    "拍张照",
    "核心功能",
    "训练效果",
    "真实动作库",
    "1324",
    "联系我们",
]


def test_landing_page_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    for marker in LANDING_SECTIONS:
        assert marker in body, f"落地页缺少区块/文案：{marker}"
    # 独立样式表已挂载，且包含品牌主色
    assert "/static/css/landing.css" in body
    css = client.get("/static/css/landing.css")
    assert css.status_code == 200
    assert "#c6f135" in css.text.lower()


def test_landing_download_placeholder_when_unset(client, monkeypatch):
    monkeypatch.setattr(settings, "landing_android_download_url", "", raising=False)
    resp = client.get("/")
    assert resp.status_code == 200
    # 未配置时不出现外链下载按钮
    assert 'href="https://' not in resp.text.split("现在就开始")[1].split("</section>")[0]
    assert "即将开放" in resp.text


def test_landing_download_link_when_configured(client, monkeypatch):
    monkeypatch.setattr(
        settings,
        "landing_android_download_url",
        "https://releases.formfit.app/formfit-latest.apk",
        raising=False,
    )
    resp = client.get("/")
    assert resp.status_code == 200
    assert "https://releases.formfit.app/formfit-latest.apk" in resp.text
    assert "即将开放" not in resp.text


def test_landing_contact_info(client):
    resp = client.get("/")
    assert settings.landing_contact_email in resp.text
    assert settings.landing_contact_wechat in resp.text


def test_api_index_discovery(client):
    # 原根路径 JSON 接口发现信息迁移到 /api
    resp = client.get("/api")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == settings.app_name
    assert data["endpoints"]["auth"] == "/api/auth"
