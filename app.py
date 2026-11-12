# -*- coding: utf-8 -*-
"""菜篮子价格解读器 — Streamlit 版（可直接部署到 Streamlit Cloud）

数据（已打包进仓库，应用启动即读，不依赖外网抓取）：
  data/cat_*.csv      14 个品类历史价格（期货/指数，已折算为 元/公斤）
  data/realtime.json  当日批发市场价格（农业农村部 pfsc.agri.cn）

兼容说明：数据文件既可能在 data/ 子目录，也可能在仓库根目录；
本程序会按「data/ → 根目录 → 仓库在线 raw」的顺序查找，任一处存在即可。
"""
import os
import io
import json
import urllib.request

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

WS = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(WS, "data")

# 仓库在线 raw 地址（兜底：本地找不到时从 GitHub 拉，需联网）
RAW_BASE = "https://raw.githubusercontent.com/YJH12345-y/vegetable-basket-price-interpreter/main"

# ── 品类定义：key, emoji, 展示名, 折算系数（原始单位 -> 元/公斤）────────────
META = [
    ("pork",         "🐷", "猪肉",       1 / 1000),
    ("egg",          "🥚", "鸡蛋",       1 / 500),
    ("corn",         "🌽", "玉米",       1 / 1000),
    ("soybean",      "🫘", "大豆",       1 / 1000),
    ("soymeal",      "🌾", "豆粕",       1 / 1000),
    ("soybean_oil",  "🫙", "豆油",       1 / 1000),
    ("palm_oil",     "🌴", "棕榈油",     1 / 1000),
    ("rapeseed_oil", "🥬", "菜籽油",     1 / 1000),
    ("sugar",        "🍬", "白糖",       1 / 1000),
    ("apple",        "🍎", "苹果",       1 / 1000),
    ("jujube",       "🌰", "红枣",       1 / 1000),
    ("rapeseed_meal","🌿", "菜粕",       1 / 1000),
    ("rice",         "🍚", "粳米",       1 / 1000),
    ("caolanzi",     "🧺", "菜篮子指数", 1),
]

REGIONS = [
    dict(name="东部", color="#2F7A5B", provs="京津冀 沪 苏 浙 闽 鲁 粤 琼",
         why="消费力强、冷链发达，海鲜与反季蔬菜选择多"),
    dict(name="南部", color="#E8833A", provs="皖 赣 豫 鄂 湘 桂",
         why="蔬菜主产区、产地近，鲜菜价格常年偏低"),
    dict(name="西部", color="#4A76A8", provs="蒙 渝 川 黔 滇 藏 陕 甘 青 宁 新",
         why="运输半径长，鲜菜鲜果外运成本抬高价格"),
    dict(name="北部", color="#B0555F", provs="晋 辽 吉 黑",
         why="冬季寒冷依赖外运与大棚，鲜菜季节性价差大"),
]


def _remote_text(rel):
    """从仓库在线 raw 拉取文本；失败返回 None。"""
    try:
        req = urllib.request.Request(
            f"{RAW_BASE}/{rel}",
            headers={"User-Agent": "streamlit-app"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_hist(key, conv):
    """读取某品类历史 CSV，返回 (df, 最新价, 历史分位%, 近30日涨跌%)。
    查找顺序：data/cat_{key}.csv → 根目录 cat_{key}.csv → 在线 raw。"""
    local_cands = [
        os.path.join(DATA, f"cat_{key}.csv"),
        os.path.join(WS, f"cat_{key}.csv"),
    ]
    text = None
    for p in local_cands:
        if os.path.exists(p):
            text = open(p, encoding="utf-8").read()
            break
    if text is None:
        text = _remote_text(f"cat_{key}.csv")
        if text is None:
            text = _remote_text(f"data/cat_{key}.csv")
    if not text:
        return pd.DataFrame(), None, None, None

    df = pd.read_csv(io.StringIO(text))
    df = df.dropna()
    df["date"] = pd.to_datetime(df.iloc[:, 0], errors="coerce")
    df["price"] = pd.to_numeric(df.iloc[:, 1], errors="coerce") * conv
    df = df.dropna().sort_values("date").reset_index(drop=True)
    if df.empty:
        return df, None, None, None
    prices = df["price"].to_numpy()
    last = float(prices[-1])
    # 当前价在历史中的分位：越低代表现在越便宜
    pct = float((prices < last).sum()) / len(prices) * 100
    chg30 = round((last / prices[max(0, len(prices) - 31)] - 1) * 100, 1) if len(prices) > 31 else 0.0
    return df, round(last, 2), round(pct), chg30


@st.cache_data(show_spinner=False)
def load_realtime():
    """读取当日价格；查找顺序：data/realtime.json → 根目录 realtime.json → 在线 raw。"""
    local_cands = [
        os.path.join(DATA, "realtime.json"),
        os.path.join(WS, "realtime.json"),
    ]
    for p in local_cands:
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    txt = _remote_text("realtime.json")
    if txt is None:
        txt = _remote_text("data/realtime.json")
    if txt:
        try:
            return json.loads(txt)
        except Exception:
            return {}
    return {}


def find_price(items, name, default):
    """在家庭相关列表中按名称模糊匹配价格（如「猪肉」匹配「猪肉(白条猪)」）。"""
    for it in items:
        n = it.get("name", "")
        if name in n or n in name:
            return float(it["price"])
    return default


def find_item(items, name, default_price):
    """返回 (价格, 环比%)；按名称模糊匹配，未匹配则用默认价、环比记 0。"""
    for it in items:
        n = it.get("name", "")
        if name in n or n in name:
            return float(it["price"]), float(it.get("hbs", 0))
    return default_price, 0.0


# 每人每月参考消费量（公斤/月）与默认参考价（数据缺失时回退）
_BASKET_BASE = [
    ("猪肉", 2.5, 15.0),
    ("鸡蛋", 1.5, 9.5),
    ("白条鸡", 1.0, 18.0),
    ("大白菜", 4.0, 3.0),
    ("茄子", 2.0, 5.0),
    ("芹菜", 1.5, 3.0),
    ("香蕉", 2.0, 5.0),
    ("粳米", 6.0, 6.0),
    ("豆油", 1.0, 11.0),
]

# 饮食偏好对各类用量的缩放系数
_PROFILES = {
    "标准家庭": {},
    "有孩/老人·清淡": {"猪肉": 0.8, "白条鸡": 0.8, "大白菜": 1.3, "茄子": 1.3,
                        "芹菜": 1.3, "鸡蛋": 1.2, "香蕉": 1.1, "粳米": 1.1},
    "肉食偏好": {"猪肉": 1.4, "白条鸡": 1.4, "大白菜": 0.9, "茄子": 0.9, "芹菜": 0.9},
}


def family_basket(today, profile="标准家庭"):
    """计算家庭菜篮子：返回 (每人每月支出, 每日每人涨跌影响, 明细DataFrame)。
    明细含 品类/用量/单价/月支出/今日日影响。"""
    fac = _PROFILES.get(profile, {})
    rows, per_person_month, per_person_day_delta = [], 0.0, 0.0
    for name, qty, default in _BASKET_BASE:
        price, hbs = find_item(today, name, default)
        q = qty * fac.get(name, 1.0)
        month_cost = price * q                       # 每人每月支出（q 已是月度用量）
        yest = price / (1 + hbs / 100) if hbs != 0 else price
        day_delta = (price - yest) * (q / 30)        # 每人每日影响（元/天）
        per_person_month += month_cost
        per_person_day_delta += day_delta
        rows.append(dict(品类=name, 用量_kg=round(q, 2), 单价=round(price, 2),
                         月支出=round(month_cost, 1), 今日日影响=round(day_delta, 3)))
    return per_person_month, per_person_day_delta, pd.DataFrame(rows)


def main():
    st.set_page_config(page_title="菜篮子价格解读器", page_icon="🧺", layout="wide")
    st.title("🧺 菜篮子价格解读器")
    st.caption("基于农业农村部批发市场价格 + 期货历史数据，帮你读懂每天的「菜篮子」")

    # ───────── 侧边栏：我的家庭（互动输入）─────────
    st.sidebar.header("🏠 我的家庭")
    st.sidebar.caption("填入您家情况，下方自动测算物价影响")
    income = st.sidebar.number_input("家庭月总收入（元）", min_value=0,
                                     value=8000, step=500, key="income")
    members = st.sidebar.number_input("家庭人口（人）", min_value=1, max_value=20,
                                      value=3, step=1, key="members")
    profile = st.sidebar.selectbox("家庭饮食偏好", list(_PROFILES.keys()), index=0,
                                   key="profile")

    rt = load_realtime()
    fetch_time = rt.get("fetch_time", "未知")
    report_date = rt.get("report_date", "")

    # ───────── 模块一：今日菜篮子 ─────────
    st.header("📅 今日菜篮子", divider="green")
    col1, col2 = st.columns([2, 1])
    with col2:
        st.metric("数据更新时间", fetch_time)
        if report_date:
            st.caption(f"周度均价基准日：{report_date}")

    # 合并当日价与周均价，去重（优先保留带环比的当日价）
    raw = (rt.get("growth", []) or []) + (rt.get("report", []) or [])
    seen, today = set(), []
    for x in raw:
        n = x.get("name", "")
        if n and n not in seen and x.get("price"):
            seen.add(n)
            today.append(dict(
                name=n,
                price=round(float(x["price"]), 2),
                hbs=round(float(x.get("hbs", 0)), 1),
            ))

    with col1:
        if today:
            df_today = pd.DataFrame(today).sort_values("price", ascending=False)
            st.dataframe(
                df_today.rename(columns={"name": "品类", "price": "价格(元/公斤)", "hbs": "环比%"}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("未找到当日价格数据，请确认 realtime.json 已上传到仓库根目录或 data/ 文件夹。")

    # 农产品批发价格指数
    indices = rt.get("indices", []) or []
    if indices:
        st.subheader("📊 农产品批发价格指数")
        cols = st.columns(min(len(indices), 4))
        for i, idx in enumerate(indices[:4]):
            val = idx.get("value")
            yest = idx.get("yesterday")
            delta = round(float(val) - float(yest), 2) if val is not None and yest is not None else None
            cols[i].metric(idx.get("name", f"指数{i}"), val, delta)

    # 家庭每日菜篮子成本 + 涨跌榜
    if today:
        basket = round(
            find_price(today, "猪肉", 15) * 0.12
            + find_price(today, "鸡蛋", 9.7) * 0.10
            + find_price(today, "白条鸡", 18) * 0.08
            + find_price(today, "大白菜", 3) * 0.5
            + find_price(today, "苹果", 8) * 0.25
            + find_price(today, "粳米", 6) * 0.30, 1
        )
        ups = sorted([t for t in today if t["hbs"] > 0], key=lambda d: -d["hbs"])[:3]
        downs = sorted([t for t in today if t["hbs"] < 0], key=lambda d: d["hbs"])[:3]

        c1, c2, c3 = st.columns(3)
        c1.metric("👨‍👩‍👧 家庭每日菜篮子成本", f"¥{basket}", "按参考用量折算")
        with c2:
            st.markdown("**🔺 今日领涨**")
            for t in ups:
                st.markdown(f"- {t['name']}　{t['price']} 元/公斤　`+{t['hbs']}%`")
        with c3:
            st.markdown("**🔻 今日领跌**")
            for t in downs:
                st.markdown(f"- {t['name']}　{t['price']} 元/公斤　`{t['hbs']}%`")

    # ───────── 模块四：我的家庭影响测算（互动）─────────
    if today:
        st.header("💡 我的家庭影响测算", divider="green")
        st.markdown(f"按您在左侧填写的 **{members} 人家庭 / 月收入 ¥{income:,.0f} / "
                    f"{profile}**，结合今日批发价，自动测算物价对您家的影响。")

        per_person_month, per_person_day, df_basket = family_basket(today, profile)
        fam_month = per_person_month * members
        fam_day_delta = per_person_day * members
        fam_month_delta = fam_day_delta * 30
        ratio = fam_month / max(income, 1)

        m1, m2, m3 = st.columns(3)
        m1.metric("🛒 家庭每月菜篮子支出", f"¥{fam_month:,.0f}",
                  f"按 {members} 人 × 今日价折算")
        m2.metric("📊 占月收入比例", f"{ratio*100:.1f}%",
                  "比重越低越轻松" if ratio < 0.3 else ("比重偏高" if ratio < 0.5 else "比重较大"))
        sign = "🔺多花" if fam_day_delta >= 0 else "🔻少花"
        m3.metric("🌡️ 今日物价对您家影响", f"{sign} ¥{abs(fam_day_delta):.2f}/天",
                  f"按月约{'多花' if fam_month_delta >= 0 else '少花'} ¥{abs(fam_month_delta):.0f}")

        # 分品类明细 + 柱状图
        c_left, c_right = st.columns([3, 2])
        with c_left:
            st.dataframe(df_basket.rename(columns={
                "品类": "品类", "用量_kg": "用量(公斤/月·人)", "单价": "单价(元/公斤)",
                "月支出": "月支出(元/人)", "今日日影响": "今日日影响(元/人)"}),
                use_container_width=True, hide_index=True)
        with c_right:
            fig2 = px.bar(df_basket, x="品类", y="月支出",
                          title="各类别每月支出（每人）", color="月支出",
                          color_continuous_scale="Tealgrn")
            fig2.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=300)
            st.plotly_chart(fig2, use_container_width=True)

        # 结论文案
        if fam_day_delta >= 0:
            impact_txt = (f"与昨日相比，今天的菜价让您的家庭每天大约**多花 ¥{fam_day_delta:.2f}**"
                          f"（按月约 ¥{fam_month_delta:.0f}）。")
        else:
            impact_txt = (f"与昨日相比，今天的菜价让您的家庭每天大约**少花 ¥{abs(fam_day_delta):.2f}**"
                          f"（按月约省 ¥{abs(fam_month_delta):.0f}）。")
        if ratio < 0.15:
            verdict = "菜篮子支出占收入比重很低，日常物价波动对您家影响很小，可以放宽心。"
        elif ratio < 0.3:
            verdict = "菜篮子支出占收入比重处于合理区间，物价波动在可承受范围内。"
        elif ratio < 0.5:
            verdict = "菜篮子支出占收入比重偏高，建议多关注领涨品类、错峰采购或选性价比更高的替代品。"
        else:
            verdict = "菜篮子支出已占收入较大比重，物价上涨会明显加重生活压力，建议优先囤米面油等耐储品类。"
        st.info(f"{impact_txt}\n\n{verdict}")

    # ───────── 模块二：历史价格走势 ─────────
    st.header("📈 历史价格走势", divider="green")
    st.markdown("选择品类，查看长期价格曲线与「现在贵不贵」解读。")
    labels = {m[2]: m for m in META}
    choice = st.selectbox("选择品类", list(labels.keys()), index=0)
    key, emoji, name, conv = labels[choice]

    df, last, pct, chg30 = load_hist(key, conv)
    if df.empty:
        st.warning(f"未找到 {name} 的历史数据文件 cat_{key}.csv（请放在仓库根目录或 data/ 文件夹）")
    else:
        # 抽样，控制点数 ~400，保证流畅
        if len(df) > 400:
            step = len(df) // 400
            df_plot = df.iloc[::step].copy()
            df_plot = pd.concat([df_plot, df.iloc[[-1]]])
        else:
            df_plot = df

        m1, m2, m3 = st.columns(3)
        m1.metric(f"{emoji} 最新价", f"{last} {'元/公斤' if conv != 1 else '点'}")
        m2.metric("历史分位", f"{pct}%",
                  "处于历史低位，现在偏便宜" if pct < 33 else ("处于历史高位，现在偏贵" if pct > 66 else "处于历史中位"))
        m3.metric("近 30 日涨跌", f"{chg30}%")

        fig = px.line(df_plot, x="date", y="price",
                      title=f"{name} 历史价格走势",
                      labels={"date": "日期", "price": "价格(元/公斤)" if conv != 1 else "指数"})
        fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=380)
        fig.update_traces(line=dict(width=2))
        st.plotly_chart(fig, use_container_width=True)

    # ───────── 模块三：区域解读 ─────────
    st.header("🗺️ 四大区域菜价解读", divider="green")
    rcols = st.columns(4)
    for i, r in enumerate(REGIONS):
        with rcols[i]:
            st.markdown(f"**<span style='color:{r['color']}'>{r['name']}</span>**", unsafe_allow_html=True)
            st.caption(r["provs"])
            st.write(r["why"])

    st.divider()
    st.caption("数据来源：农业农村部全国农产品批发市场价格信息系统（pfsc.agri.cn）、期货交易所历史行情。"
               "本应用为课程演示用途，价格仅供参考。")


if __name__ == "__main__":
    main()
