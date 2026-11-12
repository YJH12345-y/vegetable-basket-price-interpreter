# -*- coding: utf-8 -*-
"""用 Personal Access Token 把「自动刷新」所需的几个文件推到 GitHub 仓库。

用法（在本机终端）：
    set GITHUB_TOKEN=ghp_你的token
    python push_all.py

会创建/更新：
    app.py, data_fetcher.py, refresh_data.py, requirements.txt,
    .github/workflows/daily_refresh.yml
（数据文件 cat_*.csv / realtime.json 已在仓库，不重复传）
"""
import os
import base64
import json
import urllib.request

REPO = "YJH12345-y/vegetable-basket-price-interpreter"
BRANCH = "main"
TOKEN = os.environ.get("GITHUB_TOKEN")
WS = os.path.dirname(os.path.abspath(__file__))

FILES = [
    ("app.py", "app.py"),
    ("data_fetcher.py", "data_fetcher.py"),
    ("refresh_data.py", "refresh_data.py"),
    ("requirements.txt", "requirements.txt"),
    (".github/workflows/daily_refresh.yml", ".github/workflows/daily_refresh.yml"),
]


def api(method, path, body=None):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}",
                 "User-Agent": "push-script",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def get_sha(path):
    try:
        d = json.loads(api("GET", f"contents/{path}?ref={BRANCH}"))
        return d.get("sha")
    except Exception:
        return None


def put(path, content, sha):
    body = {"message": f"add daily auto-refresh: {path}",
            "content": base64.b64encode(content).decode(),
            "branch": BRANCH}
    if sha:
        body["sha"] = sha
    api("PUT", f"contents/{path}", body)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ 请先设置环境变量 GITHUB_TOKEN=你的token")
        raise SystemExit(1)
    for local, repo in FILES:
        p = os.path.join(WS, local)
        if not os.path.exists(p):
            print("跳过（本地缺失）:", local)
            continue
        content = open(p, "rb").read()
        sha = get_sha(repo)
        put(repo, content, sha)
        print("✅ 已推送:", repo, "(更新)" if sha else "(新建)")
    print("\n全部完成。GitHub Actions 会按北京时间每天 01:00 自动刷新；")
    print("可到仓库的 Actions 标签页查看运行记录。")
