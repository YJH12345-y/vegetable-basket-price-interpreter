# -*- coding: utf-8 -*-
"""菜篮子实时数据抓取（农业农村部 pfsc.agri.cn + agri.cn 周度动态）。

仅依赖 requests，供两处共用：
  - refresh_data.py  ：GitHub Actions 每日自动刷新并写回 realtime.json
  - app.py           ：网页上的「🔄 刷新实时数据」按钮，手动联网获取最新价

数据字段与仓库内 realtime.json 完全兼容。
"""
import os
import re
import json
import datetime

# 去掉可能干扰境外访问的代理环境变量（GitHub Runner / 本机 alike）
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

import requests

BASE = "https://pfsc.agri.cn"
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": BASE + "/",
    "Content-Type": "application/json;charset=UTF-8",
}
HH = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_growth():
    """当日涨跌幅排行：20 个真实当日批发价（元/公斤）。"""
    r = requests.post(BASE + "/price_portal/index/growthRanking", headers=H, json={}, timeout=20)
    d = r.json()["data"]
    items = []
    for i in range(len(d["names"])):
        items.append({
            "name": d["names"][i], "code": d["codes"][i],
            "price": float(d["avgPrice"][i]),
            "hbs": float(d["priceHbs"][i]),            # 环比 %
            "last": float(d["lastAvgPrice"][i]),
            "diff": float(d["difAvgPrice"][i]),
            "date": d["date"][i], "unit": d["meteringUnit"][i],
        })
    return items


def fetch_report():
    """agri.cn 周度市场动态：肉蛋鱼真实周均价（元/公斤）。失败返回空，不影响主流程。"""
    try:
        r = requests.get("https://www.agri.cn/sj/jcyj/", headers=HH, timeout=20)
        r.encoding = r.apparent_encoding
        m = re.findall(r'href="(\./20\d{4}/t20\d{6}_\d+\.htm)"', r.text)
        if not m:
            return [], None
        url = "https://www.agri.cn/sj/jcyj/" + m[0].lstrip("./")
        um = re.search(r"t(\d{4})(\d{2})(\d{2})_", url)
        report_date = f"{um.group(1)}-{um.group(2)}-{um.group(3)}" if um else None
        r2 = requests.get(url, headers=HH, timeout=20)
        r2.encoding = r2.apparent_encoding
        txt = re.sub(r"<[^>]+>", "", r2.text)
        items, seen = [], set()

        def add(name, price):
            name = name.strip("、和的据监测重点")
            if not name or name in seen or "种" in name or len(name) > 6:
                return
            seen.add(name)
            items.append({"name": name, "price": float(price), "src": "week"})

        for name, price in re.findall(r"([一-龥A-Za-z()（）]{2,8}?)批发市场周均价每公斤([0-9.]+)元", txt):
            add(name, price)
        for names_s, prices_s in re.findall(
                r"([一-龥、和]{2,50}?)批发市场周均价每公斤分别为([0-9.]+元(?:、[0-9.]+元)*和[0-9.]+元)", txt):
            names = [n for n in re.split(r"[、和]", names_s) if n]
            prices = [float(x) for x in re.findall(r"[0-9.]+", prices_s)]
            for n, p in zip(names, prices):
                add(n, p)
        return items, report_date
    except Exception as e:
        print("report fail:", e)
        return [], None


def fetch_indices():
    """农产品批发价格指数（当日 / 昨日）。"""
    r = requests.post(BASE + "/price_portal/pi-info-day/getIndexByLevel", headers=H, json={}, timeout=20)
    d = r.json()["content"]
    out = []
    for group in d:
        for rec in (group or []):
            out.append({
                "name": rec.get("indexName"), "value": rec.get("indexValue"),
                "yesterday": rec.get("nextRecordValue"),
                "date": (rec.get("publishDate") or "")[:10],
            })
    return out


def fetch_all():
    """抓取全部当日数据，返回与 realtime.json 兼容的 dict。"""
    growth = fetch_growth()
    report, report_date = fetch_report()
    indices = fetch_indices()
    return {
        "growth": growth,
        "report": report,
        "report_date": report_date,
        "indices": indices,
        "fetch_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


if __name__ == "__main__":
    data = fetch_all()
    print("growth:", len(data["growth"]), "report:", len(data["report"]),
          "indices:", len(data["indices"]), "time:", data["fetch_time"])
