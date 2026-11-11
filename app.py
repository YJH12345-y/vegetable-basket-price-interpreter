# -*- coding: utf-8 -*-
"""菜篮子价格解读器 — Streamlit 版（可直接部署到 Streamlit Cloud）
数据：
  data/cat_*.csv      14 个品类历史价格（期货/指数，已折算为 元/公斤）
  data/realtime.json  当日批发市场价格（农业农村部 pfsc.agri.cn）
说明：本地运行 fetch_hist.py / fetch_realtime.py 可刷新数据后重新部署。
"""
import os
import json

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

WS = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(WS, "data")

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

WANTED = ["猪肉", "牛肉", "羊肉", "鸡蛋", "白条鸡", "鲤鱼", "大带鱼", "大黄花鱼",
          "花鲢活鱼", "草鱼", "鲫鱼", "白鲢鱼", "油菜", "芹菜", "大白菜", "土豆",
          "黄瓜", "西红柿", "茄子", "青椒", "苹果", "香蕉", "富士苹果"]


@st.cache_data
def load_hist(key, conv):
    """读取某品类历史 CSV，返回 (df, 最新价, 历史分位%, 近30日涨跌%)。"""
    df = pd.read_csv(os.path.join(DATA, f"cat_{key}.csv"))
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


@st.cache_data
def load_realtime():
    path = os.path.join(DATA, "realtime.json")
    if not os.path.exists(path):
        return {}
    return json.load(open(path, encoding="utf-8"))


def find_price(items, name, default):
    """在家庭相关列表中按名称模糊匹配价格（如「猪肉」匹配「猪肉(白条猪)」）。"""
    for it in items:
        n = it.get("name", "")
        if name in n or n in name:
            return float(it["price"])
    return default


def main():
    st.set_page_config(page_title="菜篮子价格解读器", page_icon="🧺", layout="wide")
    st.title("🧺 菜篮子价格解读器")
    st.caption("基于农业农村部批发市场价格 + 期货历史数据，帮你读懂每天的「菜篮子」")

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
            st.info("未找到当日价格数据，请确认 data/realtime.json 已上传。")

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

    # ───────── 模块二：历史价格走势 ─────────
    st.header("📈 历史价格走势", divider="green")
    st.markdown("选择品类，查看长期价格曲线与「现在贵不贵」解读。")
    labels = {m[2]: m for m in META}
    choice = st.selectbox("选择品类", list(labels.keys()), index=0)
    key, emoji, name, conv = labels[choice]

    df, last, pct, chg30 = load_hist(key, conv)
    if df.empty:
        st.warning(f"未找到 {name} 的历史数据文件 data/cat_{key}.csv")
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
