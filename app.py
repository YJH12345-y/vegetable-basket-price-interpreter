# -*- coding: utf-8 -*-
"""菜篮子价格解读器 — Streamlit 版（互动画像 + 游戏化版）

数据（已打包进仓库，应用启动即读，不依赖外网抓取）：
  data/cat_*.csv      14 个品类历史价格（期货/指数，已折算为 元/公斤）
  data/realtime.json  当日批发市场价格（农业农村部 pfsc.agri.cn）

本版本在原有数据逻辑上新增：
  1. 画像实验室：收入/人口/年龄/地区/城市/饮食/健康目标/烹饪/预算/渠道/权重等多维画像
  2. 随机画像盲盒、画像完成度、人设徽章、雷达图、成就系统
  3. 今日战报卡、价格温度计、省钱挑战、领涨领跌条形图、历史均线标注
  4. 统一颜色语义：涨价红、跌价绿；口径说明与方法折叠区
"""
import os
import io
import json
import random
import urllib.request

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 联网抓取模块（仅在有 requests 时启用手动刷新按钮）
try:
    import data_fetcher
    _HAS_LIVE = True
except Exception:
    _HAS_LIVE = False

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

# 演示性价格修正系数（非官方统计，仅用于画像模拟，页面会明确标注）
REGION_FACTOR = {"东部": 1.08, "南部": 0.95, "西部": 1.05, "北部": 1.02}
CITY_FACTOR = {"一线城市": 1.12, "新一线/二线": 1.05, "三线/县城": 0.96, "乡镇/农村": 0.92}
CHANNEL_FACTOR = {"菜市场": 1.00, "超市": 1.03, "社区团购": 0.96, "外卖/即时零售": 1.08}

# ── 人设预设：每个预设都是一组画像参数 ────────────────────────────────
_BASE_STATE = dict(
    income=8000, members=3, age="31-40", region="东部", city="新一线/二线",
    diet="均衡", health=[], cooking="天天做", budget="适中", channel="菜市场",
    stock="少量多次", meat_w=1.0, veg_w=1.0, staple_w=1.0, fruit_w=1.0, egg_w=1.0,
)


def _state(**kw):
    d = dict(_BASE_STATE)
    d.update(kw)
    return d


PERSONAS = {
    "标准家庭": dict(emoji="🧺", desc="不折腾，稳稳当当", state=_state()),
    "有娃家庭": dict(emoji="🧒", desc="娃要吃好，钱包别太痛", state=_state(
        income=11000, members=4, age="31-40", diet="均衡", health=["控糖"],
        fruit_w=1.3, egg_w=1.2, veg_w=1.1)),
    "银发二人组": dict(emoji="🍵", desc="清淡养生，精打细算", state=_state(
        income=6500, members=2, age="60岁以上", diet="清淡", health=["控盐", "控糖"],
        budget="斤斤计较", channel="菜市场", meat_w=0.8, veg_w=1.2, staple_w=1.1, fruit_w=1.1)),
    "独居青年": dict(emoji="🥡", desc="一个人也要好好吃饭", state=_state(
        income=6000, members=1, age="22-30", city="一线城市", cooking="外卖多",
        channel="外卖/即时零售", stock="少量多次", meat_w=0.9, veg_w=0.8,
        staple_w=0.7, fruit_w=0.9, egg_w=0.9)),
    "健身增肌党": dict(emoji="💪", desc="蛋白拉满，热量算清", state=_state(
        income=12000, members=2, age="22-30", diet="高蛋白", health=["增肌"],
        cooking="天天做", meat_w=1.6, egg_w=1.4, staple_w=1.2, veg_w=1.1)),
    "肉食爱好者": dict(emoji="🥩", desc="无肉不欢，快乐优先", state=_state(
        income=9000, members=3, diet="肉食", meat_w=1.7, veg_w=0.8,
        fruit_w=0.8, egg_w=1.1)),
    "极简省钱派": dict(emoji="🕵️", desc="每一分钱都要花在刀刃上", state=_state(
        income=5000, members=2, budget="斤斤计较", channel="社区团购", stock="月度囤货",
        meat_w=0.7, staple_w=1.2, fruit_w=0.8, veg_w=1.1)),
}

# ── 背景主题：每个画像一套底色 + 花纹 ──────────────────────────────
# ink_rgb 用于生成淡雅花纹，c1/c2 是主渐变，side 是侧边栏底色
THEMES = {
    "标准家庭": dict(c1="#FFF9ED", c2="#F2E8D5", side="#EFE4CE",
                  ink="#2F7A5B", ink_rgb="47,122,91", pattern="dots"),
    "有娃家庭": dict(c1="#FFF6DF", c2="#FFE9B8", side="#FBE3AD",
                  ink="#C2661E", ink_rgb="194,102,30", pattern="dots"),
    "银发二人组": dict(c1="#EEF8F3", c2="#DCEFE5", side="#D4E9DE",
                   ink="#2F7A5B", ink_rgb="47,122,91", pattern="grid"),
    "独居青年": dict(c1="#F5F0FC", c2="#E6DCF5", side="#DFD2EF",
                  ink="#6B4FA0", ink_rgb="107,79,160", pattern="stripes"),
    "健身增肌党": dict(c1="#FFF2EE", c2="#FADFD6", side="#F5D3C8",
                   ink="#B0453A", ink_rgb="176,69,58", pattern="chevron"),
    "肉食爱好者": dict(c1="#FCF0EA", c2="#F2DCD0", side="#EBD0C2",
                   ink="#964636", ink_rgb="150,70,54", pattern="waves"),
    "极简省钱派": dict(c1="#F3F6F0", c2="#E5EBDF", side="#DDE5D5",
                   ink="#4A6B3D", ink_rgb="74,107,61", pattern="grid"),
}

PATTERN_LABEL = {
    "dots": "圆点", "grid": "网格", "stripes": "斜纹",
    "chevron": "人字纹", "waves": "波纹",
}


def _pattern_css(kind, color):
    """返回 (background-image 值, background-size 值)。"""
    if kind == "dots":
        return f"radial-gradient({color} 1.4px, transparent 1.5px)", "26px 26px"
    if kind == "grid":
        return (f"linear-gradient({color} 1px, transparent 1px),"
                f"linear-gradient(90deg, {color} 1px, transparent 1px)"), "34px 34px"
    if kind == "stripes":
        return (f"repeating-linear-gradient(45deg, transparent 0, transparent 16px,"
                f" {color} 16px, {color} 18px)"), "auto"
    if kind == "chevron":
        return (f"repeating-linear-gradient(135deg, transparent 0, transparent 14px,"
                f" {color} 14px, {color} 16px)"), "auto"
    if kind == "waves":
        return (f"radial-gradient(circle at 18% 12%, {color} 0, transparent 36%),"
                f"radial-gradient(circle at 82% 88%, {color} 0, transparent 40%)"), "auto"
    return "none", "auto"


def theme_css(name):
    """生成整页主题 CSS（单行，避免 React removeChild 报错）。"""
    t = THEMES.get(name, THEMES["标准家庭"])
    img, size = _pattern_css(t["pattern"], f"rgba({t['ink_rgb']},0.07)")
    base = f"linear-gradient(135deg,{t['c1']} 0%,{t['c2']} 100%)"
    return (
        f'<style>.stApp{{background:{base};background-image:{img},{base};'
        f'background-size:{size},cover;background-attachment:fixed;}}'
        f'section[data-testid="stSidebar"]{{background:{t["side"]};}}'
        f'h1{{color:{t["ink"]};}}</style>'
    )


# 每人每月参考消费量（公斤/月·人）与分组
_BASKET_BASE = [
    ("猪肉",   2.5, 15.0, "肉蛋"),
    ("鸡蛋",   1.5,  9.5, "蛋奶"),
    ("白条鸡", 1.0, 18.0, "肉蛋"),
    ("大白菜", 4.0,  3.0, "蔬菜"),
    ("茄子",   2.0,  5.0, "蔬菜"),
    ("芹菜",   1.5,  3.0, "蔬菜"),
    ("土豆",   3.0,  3.5, "蔬菜"),
    ("西红柿", 2.0,  6.0, "蔬菜"),
    ("香蕉",   2.0,  5.0, "水果"),
    ("苹果",   2.0,  8.0, "水果"),
    ("粳米",   6.0,  6.0, "主食"),
    ("豆油",   1.0, 11.0, "主食"),
]

# 常见品类缺数据时的参考价（元/公斤）
_DEFAULT_PRICE = {
    "猪肉": 15, "牛肉": 60, "羊肉": 60, "鸡蛋": 9.5, "白条鸡": 18, "大白菜": 3,
    "土豆": 3.5, "西红柿": 6, "黄瓜": 5, "芹菜": 3, "茄子": 5, "粳米": 6,
    "豆油": 11, "苹果": 8, "香蕉": 5, "鲤鱼": 14, "草鱼": 16,
}

_SUBSTITUTES = {
    "猪肉": "鸡蛋 / 白条鸡", "牛肉": "猪肉 / 鸡蛋", "羊肉": "白条鸡 / 鸡蛋",
    "鸡蛋": "豆制品", "大白菜": "土豆 / 芹菜", "茄子": "西红柿 / 芹菜",
    "芹菜": "大白菜 / 土豆", "苹果": "香蕉", "香蕉": "苹果",
}


def _remote_text(rel):
    """从仓库在线 raw 拉取文本；失败返回 None。"""
    try:
        req = urllib.request.Request(
            f"{RAW_BASE}/{rel}", headers={"User-Agent": "streamlit-app"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_hist(key, conv):
    """读取某品类历史 CSV，返回 (df, 最新价, 历史分位%, 近30日涨跌%)。"""
    local_cands = [os.path.join(DATA, f"cat_{key}.csv"), os.path.join(WS, f"cat_{key}.csv")]
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

    df = pd.read_csv(io.StringIO(text)).dropna()
    df["date"] = pd.to_datetime(df.iloc[:, 0], errors="coerce")
    df["price"] = pd.to_numeric(df.iloc[:, 1], errors="coerce") * conv
    df = df.dropna().sort_values("date").reset_index(drop=True)
    if df.empty:
        return df, None, None, None
    prices = df["price"].to_numpy()
    last = float(prices[-1])
    pct = float((prices < last).sum()) / len(prices) * 100
    chg30 = round((last / prices[max(0, len(prices) - 31)] - 1) * 100, 1) if len(prices) > 31 else 0.0
    df["ma30"] = df["price"].rolling(30).mean()
    return df, round(last, 2), round(pct), chg30


# ═══════════════════════════ 深度分析引擎 ═══════════════════════════
def _load_all_hist():
    """一次性读取全部品类历史，返回 {展示名: DataFrame}。"""
    out = {}
    for key, emoji, name, conv in META:
        df, _, _, _ = load_hist(key, conv)
        if not df.empty:
            out[name] = df
    return out


load_all_hist = st.cache_data(show_spinner=False)(_load_all_hist)


def _seasonal_matrix():
    """品类 × 月份 的历史均价矩阵（按各自全样本月份归集）。"""
    data = {}
    for name, df in _load_all_hist().items():
        s = df.set_index("date")["price"].resample("MS").mean()
        bymonth = s.groupby(s.index.month).mean()
        if len(bymonth) == 12:
            data[name] = bymonth
    mat = pd.DataFrame(data).T
    mat.columns = [f"{m}月" for m in mat.columns]
    return mat


seasonal_matrix = st.cache_data(show_spinner=False)(_seasonal_matrix)


def _corr_matrix():
    """品类月度收益率相关矩阵（min_periods=24，避免短样本误判）。"""
    series = {}
    for name, df in _load_all_hist().items():
        s = df.set_index("date")["price"].resample("MS").mean().pct_change()
        series[name] = s
    return pd.DataFrame(series).corr(min_periods=24)


corr_matrix = st.cache_data(show_spinner=False)(_corr_matrix)


def risk_metrics(df):
    """返回 (年化波动率%, 最大回撤%, 近一年涨跌%)。"""
    s = df.set_index("date")["price"].sort_index()
    daily = s.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    vol = float(daily.std() * np.sqrt(252) * 100) if len(daily) > 30 else float("nan")
    mdd = float((s / s.cummax() - 1).min() * 100)
    cutoff = s.index.max() - pd.Timedelta(days=365)
    yr = s[s.index >= cutoff]
    yoy = float((yr.iloc[-1] / yr.iloc[0] - 1) * 100) if len(yr) > 20 else float("nan")
    return vol, mdd, yoy


def value_map(allh):
    """全品类估值地图：当前价在各自历史中的位置。"""
    rows = []
    for name, df in allh.items():
        last = float(df["price"].iloc[-1])
        pct = float((df["price"] < last).mean() * 100)
        yr = df[df["date"] >= df["date"].max() - pd.Timedelta(days=365)]["price"]
        avg1 = float(yr.mean()) if len(yr) else last
        rows.append(dict(品类=name, 历史分位=pct, 最新价=round(last, 2),
                         近一年均价=round(avg1, 2),
                         偏离均价=round((last / avg1 - 1) * 100, 1) if avg1 else 0.0))
    return pd.DataFrame(rows).sort_values("历史分位").reset_index(drop=True)


def forecast_price(df, horizon=30):
    """课程级线性回归外推：返回 (预测价, 下界, 上界, 日斜率, 样本天数)。"""
    y = df["price"].to_numpy(dtype=float)
    n = min(120, len(y))
    y = y[-n:]
    x = np.arange(n)
    slope, intercept = np.polyfit(x, y, 1)
    noise = float(np.std(y - (slope * x + intercept)))
    pred = float(slope * (n + horizon - 1) + intercept)
    lo = float(max(0.0, pred - 1.96 * noise))
    hi = float(pred + 1.96 * noise)
    return pred, lo, hi, float(slope), n


def build_insights(allh):
    """从历史数据自动生成 4 条有具体数字的洞察。"""
    out = []
    vm = value_map(allh)
    if len(vm) >= 2:
        c, d = vm.iloc[0], vm.iloc[-1]
        out.append(f"🟢 **{c['品类']}** 处历史 {c['历史分位']:.0f}% 分位，是相对最便宜的品类；"
                   f"🔴 **{d['品类']}** 在 {d['历史分位']:.0f}% 分位，处在高位。")

    sm = seasonal_matrix()
    if not sm.empty:
        spread = (sm.max(axis=1) / sm.min(axis=1) - 1) * 100
        name = spread.idxmax()
        lo_m, hi_m = sm.loc[name].idxmin(), sm.loc[name].idxmax()
        out.append(f"📅 **{name}** 季节性最强：{lo_m}均价最低、{hi_m}最高，"
                   f"历史价差约 **{spread[name]:.0f}%**，错峰买能省一笔。")

    risks = []
    for name, df in allh.items():
        v, mdd, _ = risk_metrics(df)
        if np.isfinite(v):
            risks.append((v, name, mdd))
    risks.sort(reverse=True)
    if risks:
        out.append(f"🎢 **{risks[0][1]}** 年化波动率 **{risks[0][0]:.0f}%**、"
                   f"最大回撤 {risks[0][2]:.0f}%，是价格最「过山车」的品类。")

    cm = corr_matrix()
    if cm is not None and cm.shape[0] > 2:
        cc = cm.where(~np.eye(len(cm), dtype=bool)).stack().dropna()
        if len(cc):
            a, b = cc.idxmax()
            out.append(f"🔗 **{a}** 与 **{b}** 月度价格同步性最高（r={cc.max():.2f}），"
                       "涨价往往结伴而来。")
    return out


@st.cache_data(show_spinner=False)
def load_realtime():
    """读取当日价格；查找顺序：data/realtime.json → 根目录 → 在线 raw。"""
    local_cands = [os.path.join(DATA, "realtime.json"), os.path.join(WS, "realtime.json")]
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
    for it in items:
        n = it.get("name", "")
        if name in n or n in name:
            return float(it["price"])
    return default


def find_item(items, name, default_price):
    for it in items:
        n = it.get("name", "")
        if name in n or n in name:
            return float(it["price"]), float(it.get("hbs", 0))
    return default_price, 0.0


def _default_price(name):
    return _DEFAULT_PRICE.get(name, 10.0)


def price_and_src(items, name, default):
    for it in items:
        n = it.get("name", "")
        if name in n or n in name:
            return float(it["price"]), "实时"
    return default, "参考"


def build_factors(state):
    """把多维画像翻译成每个品类的用量缩放系数 + 价格修正系数。"""
    f = {name: 1.0 for name, _, _, _ in _BASKET_BASE}

    diet_map = {
        "清淡": {"猪肉": 0.8, "白条鸡": 0.8, "豆油": 0.9, "大白菜": 1.2, "芹菜": 1.2},
        "均衡": {},
        "肉食": {"猪肉": 1.4, "白条鸡": 1.4, "大白菜": 0.9, "茄子": 0.9},
        "高蛋白": {"猪肉": 1.3, "鸡蛋": 1.3, "白条鸡": 1.3, "粳米": 1.1},
        "素食": {"猪肉": 0.15, "白条鸡": 0.15, "鸡蛋": 1.2, "蔬菜": 1.4},
    }
    for name, mult in diet_map.get(state["diet"], {}).items():
        if name in f:
            f[name] *= mult

    for goal in state["health"]:
        if goal == "减脂":
            f["猪肉"] *= 0.85; f["粳米"] *= 0.75; f["豆油"] *= 0.8
        elif goal == "增肌":
            f["猪肉"] *= 1.15; f["鸡蛋"] *= 1.15; f["粳米"] *= 1.1
        elif goal == "控糖":
            f["香蕉"] *= 0.7; f["苹果"] *= 0.8; f["粳米"] *= 0.9
        elif goal == "控盐":
            f["大白菜"] *= 1.1; f["芹菜"] *= 1.1
        elif goal == "素食":
            f["猪肉"] *= 0.15; f["白条鸡"] *= 0.15; f["鸡蛋"] *= 1.2

    if state["budget"] == "斤斤计较":
        f["猪肉"] *= 0.85; f["粳米"] *= 1.1; f["土豆"] *= 1.15
    elif state["budget"] == "品质优先":
        f["猪肉"] *= 1.1; f["苹果"] *= 1.15; f["鸡蛋"] *= 1.1

    if state["cooking"] == "外卖多":
        for k in f:
            f[k] *= 0.65
    elif state["cooking"] == "周末做":
        for k in f:
            f[k] *= 0.88

    if state["stock"] == "月度囤货":
        f["粳米"] *= 1.15; f["豆油"] *= 1.15

    # 自定义权重
    for name, _, _, group in _BASKET_BASE:
        key = {"肉蛋": "meat_w", "蛋奶": "egg_w", "蔬菜": "veg_w",
               "水果": "fruit_w", "主食": "staple_w"}[group]
        f[name] *= state[key]

    price_factor = (REGION_FACTOR.get(state["region"], 1.0)
                    * CITY_FACTOR.get(state["city"], 1.0)
                    * CHANNEL_FACTOR.get(state["channel"], 1.0))
    return f, round(price_factor, 3)


def family_basket(today, factors=None, price_factor=1.0):
    """返回 (每人每月支出, 每人每日涨跌影响, 明细DataFrame)。"""
    factors = factors or {}
    rows, per_person_month, per_person_day_delta = [], 0.0, 0.0
    for name, qty, default, group in _BASKET_BASE:
        price, hbs = find_item(today, name, default)
        price = price * price_factor
        q = qty * factors.get(name, 1.0)
        month_cost = price * q
        yest = price / (1 + hbs / 100) if hbs != 0 else price
        day_delta = (price - yest) * (q / 30)
        per_person_month += month_cost
        per_person_day_delta += day_delta
        rows.append(dict(品类=name, 分组=group, 用量_kg=q, 单价=price,
                         月支出=month_cost, 今日日影响=day_delta))
    df = pd.DataFrame(rows)
    return per_person_month, per_person_day_delta, df


def progress_score(state):
    diff = sum(1 for k, v in _BASE_STATE.items() if state.get(k) != v)
    return min(100, 35 + diff * 9)


def persona_badge(state):
    if state["meat_w"] >= 1.4 or state["diet"] == "肉食" or state["diet"] == "高蛋白":
        return "🥩 蛋白达人"
    if state["budget"] == "斤斤计较":
        return "🕵️ 省钱侦探"
    if "控糖" in state["health"] or "控盐" in state["health"]:
        return "🌿 养生选手"
    if state["cooking"] == "外卖多":
        return "🥡 懒人食客"
    if state["members"] == 1:
        return "🧑‍🎤 独行侠"
    return "🧺 均衡生活家"


def radar_chart(state):
    dims = ["肉食", "蔬果", "主食", "预算敏感", "烹饪投入"]
    vals = [
        min(100, state["meat_w"] / 1.8 * 100),
        min(100, (state["veg_w"] + state["fruit_w"]) / 2.6 * 100),
        min(100, state["staple_w"] / 1.5 * 100),
        {"斤斤计较": 92, "适中": 60, "品质优先": 28}[state["budget"]],
        {"天天做": 92, "周末做": 60, "外卖多": 25}[state["cooking"]],
    ]
    vals += vals[:1]
    theta = dims + dims[:1]
    fig = go.Figure(go.Scatterpolar(r=vals, theta=theta, fill="toself",
                                    line=dict(color="#2F7A5B", width=2),
                                    fillcolor="rgba(47,122,91,0.18)"))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100], showticklabels=False)),
        showlegend=False, height=300,
        margin=dict(l=30, r=30, t=20, b=20),
    )
    return fig


def apply_random_persona():
    """盲盒按钮回调：在控件实例化前写入 session_state。"""
    name = random.choice(list(PERSONAS.keys()))
    st.session_state["persona_name"] = name
    for k, v in PERSONAS[name]["state"].items():
        st.session_state[k] = v


def metric_card(title, value, delta=None, unit="", up_is_good=False, note=""):
    """自定义指标卡：统一 涨价红 / 跌价绿。"""
    if delta is None:
        color, delta_text = "#6b7280", "—"
    else:
        good = (delta > 0) if up_is_good else (delta < 0)
        color = "#1e8449" if good else "#c0392b"
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "＝")
        delta_text = f"{arrow} {abs(delta):,.2f}{unit}"
    html = (
        f'<div style="background:rgba(255,255,255,0.72);border:1px solid rgba(255,255,255,0.9);border-radius:14px;padding:14px 16px;min-height:104px;box-shadow:0 2px 10px rgba(0,0,0,0.05);backdrop-filter:blur(6px);">'
        f'<div style="font-size:13px;color:#6b7280;">{title}</div>'
        f'<div style="font-size:25px;font-weight:750;color:#111827;line-height:1.25;margin:4px 0;">{value}</div>'
        f'<div style="font-size:13px;font-weight:650;color:{color};">{delta_text}</div>'
        f'<div style="font-size:11px;color:#9ca3af;margin-top:3px;">{note}</div>'
        '</div>'
    )
    # 去掉首尾空白：否则 Streamlit 重渲染时 React 会因多余文本节点报 removeChild 错
    st.markdown(html.strip(), unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="菜篮子价格解读器", page_icon="🧺", layout="wide",
                       initial_sidebar_state="expanded")

    # 主题：默认跟随当前画像，也可手动指定
    theme_mode = st.session_state.get("theme_mode", "跟随画像")
    active_theme = (st.session_state.get("persona_name", "标准家庭")
                    if theme_mode == "跟随画像" else theme_mode)
    st.markdown(theme_css(active_theme), unsafe_allow_html=True)

    # 初始化画像参数
    for k, v in _BASE_STATE.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if "persona_name" not in st.session_state:
        st.session_state["persona_name"] = "标准家庭"

    state = {k: st.session_state[k] for k in _BASE_STATE}

    # ───────── 侧边栏：画像实验室 ─────────
    st.sidebar.title("🎮 画像实验室")
    st.sidebar.caption("挑个人设，再微调 5 组参数，解锁你的专属菜价剧本")

    st.sidebar.selectbox("🎨 背景主题", ["跟随画像"] + list(THEMES.keys()),
                         key="theme_mode")
    if theme_mode == "跟随画像":
        t = THEMES[active_theme]
        st.sidebar.caption(f"当前花纹：**{PATTERN_LABEL[t['pattern']]}** · 随「{active_theme}」自动切换")

    persona_names = list(PERSONAS.keys())
    st.sidebar.selectbox("① 先挑一个初始人设", persona_names, key="persona_name")

    st.sidebar.button("🎲 抽一个画像盲盒", on_click=apply_random_persona,
                      width="stretch")

    score = progress_score(state)
    st.sidebar.progress(score / 100)
    st.sidebar.caption(f"画像完成度 **{score}%** ｜ 当前人设：**{persona_badge(state)}**")
    st.sidebar.caption(f"{PERSONAS[st.session_state['persona_name']]['emoji']} "
                       f"{PERSONAS[st.session_state['persona_name']]['desc']}")

    with st.sidebar.expander("② 我是谁（基础）", expanded=True):
        st.number_input("家庭月总收入（元）", min_value=0, step=500, key="income")
        st.number_input("家庭人口（人）", min_value=1, max_value=20, step=1, key="members")
        st.selectbox("主要年龄段", ["22-30", "31-40", "41-50", "51-60", "60岁以上"], key="age")
        st.selectbox("所在区域", list(REGION_FACTOR.keys()), key="region")
        st.selectbox("城市层级", list(CITY_FACTOR.keys()), key="city")

    with st.sidebar.expander("③ 我爱吃什么（口味）"):
        st.selectbox("饮食偏好", ["清淡", "均衡", "肉食", "高蛋白", "素食"], key="diet")
        st.multiselect("健康目标（可多选）", ["减脂", "增肌", "控糖", "控盐", "素食"], key="health")
        st.select_slider("做饭频率", ["外卖多", "周末做", "天天做"], key="cooking")

    with st.sidebar.expander("④ 我怎么花钱（消费）"):
        st.select_slider("预算敏感度", ["斤斤计较", "适中", "品质优先"], key="budget")
        st.selectbox("主要采购渠道", list(CHANNEL_FACTOR.keys()), key="channel")
        st.selectbox("囤货习惯", ["少量多次", "每周一次", "月度囤货"], key="stock")

    with st.sidebar.expander("⑤ 自定义权重（进阶）"):
        st.caption("拖动滑块，精准调出你的食谱结构（1.0 为基准）")
        st.slider("🥩 肉食权重", 0.2, 2.0, step=0.1, key="meat_w")
        st.slider("🥬 蔬菜权重", 0.2, 2.0, step=0.1, key="veg_w")
        st.slider("🍚 主食权重", 0.2, 2.0, step=0.1, key="staple_w")
        st.slider("🍎 水果权重", 0.2, 2.0, step=0.1, key="fruit_w")
        st.slider("🥚 蛋奶权重", 0.2, 2.0, step=0.1, key="egg_w")

    state = {k: st.session_state[k] for k in _BASE_STATE}

    # ───────── 实时刷新 ─────────
    if _HAS_LIVE:
        if st.sidebar.button("🔄 刷新实时菜价", width="stretch"):
            with st.spinner("正在联网获取最新菜价…"):
                try:
                    live = data_fetcher.fetch_all()
                except Exception as e:
                    live = None
                    st.warning(f"联网获取失败：{e}")
            if live and len(live.get("growth", [])) > 0:
                st.session_state["live_rt"] = live
                st.success("已更新为最新实时数据 ✅（本次会话内生效）")
                st.rerun()

    rt = st.session_state.get("live_rt") or load_realtime()
    fetch_time = rt.get("fetch_time", "未知")
    report_date = rt.get("report_date", "")

    raw = (rt.get("growth", []) or []) + (rt.get("report", []) or [])
    seen, today = set(), []
    for x in raw:
        n = x.get("name", "")
        if n and n not in seen and x.get("price"):
            seen.add(n)
            today.append(dict(name=n, price=round(float(x["price"]), 2),
                              hbs=round(float(x.get("hbs", 0)), 1)))

    indices = rt.get("indices", []) or []
    factors, price_factor = build_factors(state)
    allh = load_all_hist()

    # ───────── 顶部：今日战报 ─────────
    st.title("🧺 菜篮子价格解读器")
    st.caption("基于农业农村部批发市场价格 + 期货历史数据，帮你把每天的菜价看成一场小游戏")

    if today:
        per_person_month, per_person_day, df_basket = family_basket(
            today, factors, price_factor)
        members = state["members"]
        income = state["income"]
        fam_month = per_person_month * members
        fam_day_delta = per_person_day * members
        fam_month_delta = fam_day_delta * 30
        ratio = fam_month / max(income, 1)

        basket_index = next((i for i in indices if "菜篮子" in i.get("name", "")), None)
        idx_val = float(basket_index["value"]) if basket_index else None
        idx_delta = (float(basket_index["value"]) - float(basket_index["yesterday"])) if basket_index else None

        st.markdown("### 🎬 今日战报")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            metric_card("🧺 菜篮子指数", f"{idx_val:.2f}" if idx_val else "—",
                        idx_delta, " 点", False, "较昨日（涨价红 / 跌价绿）")
        with c2:
            metric_card("🏠 你家每月菜钱", f"¥{fam_month:,.0f}", None,
                        note=f"{members} 人 × 画像修正系数 {price_factor}")
        with c3:
            metric_card("🌡️ 今日钱包影响",
                        f"{'少花' if fam_day_delta < 0 else '多花'} ¥{abs(fam_day_delta):.3f}/天",
                        fam_day_delta, " 元/天", False,
                        f"按月约{'省' if fam_day_delta < 0 else '多花'} ¥{abs(fam_month_delta):.0f}")
        with c4:
            level = "轻松" if ratio < 0.15 else ("可控" if ratio < 0.3 else ("偏紧" if ratio < 0.5 else "吃紧"))
            metric_card("🎯 负担等级", level, None,
                        note=f"占月收入 {ratio*100:.1f}% ｜ {persona_badge(state)}")

        # 成就徽章
        badges = []
        if ratio < 0.15:
            badges.append("🏅 预算掌控者")
        if fam_day_delta < 0:
            badges.append("🟢 今日抄底王")
        if progress_score(state) >= 80:
            badges.append("🎯 精准画像师")
        if state["diet"] in ("高蛋白", "肉食"):
            badges.append("🥩 蛋白狂人")
        if badges:
            st.markdown("**🏆 已解锁成就：** " + " ｜ ".join(f"`{b}`" for b in badges))

    # ───────── 数据洞察：直接从历史算出来 ─────────
    if allh:
        with st.container(border=True):
            st.markdown("### 🔎 数据自己会说话")
            st.caption("以下结论由 14 个品类、最长 20 年历史数据实时算出（期货/指数口径，"
                       "与今日批发现价不同），不是写死的文案。")
            for line in build_insights(allh):
                st.markdown(f"- {line}")

    # ───────── 模块一：今日菜篮子 ─────────
    st.header("📅 今日菜篮子", divider="green")
    if today:
        left, right = st.columns([2, 1])
        with right:
            st.metric("数据更新时间", fetch_time)
            if report_date:
                st.caption(f"周均价基准日：{report_date}（非单日价）")
            st.caption("数据每日自动更新，也可在左下角手动刷新")

        df_today = pd.DataFrame(today).sort_values("price", ascending=False).reset_index(drop=True)
        df_today["信号"] = df_today["hbs"].apply(lambda x: "🔺" if x > 0 else ("🔻" if x < 0 else "➖"))
        df_today = df_today[["name", "price", "hbs", "信号"]].rename(
            columns={"name": "品类", "price": "价格(元/公斤)", "hbs": "环比%"})
        with left:
            st.dataframe(
                df_today,
                width="stretch", hide_index=True, height=330,
                column_config={
                    "品类": st.column_config.TextColumn("品类", width="medium"),
                    "价格(元/公斤)": st.column_config.NumberColumn("价格(元/公斤)", format="%.2f", width="small"),
                    "环比%": st.column_config.NumberColumn("环比%", format="%+.1f%%", width="small"),
                    "信号": st.column_config.TextColumn("信号", width="small"),
                },
            )

        # 指数卡（统一颜色）
        if indices:
            st.subheader("📊 农产品批发价格指数")
            icols = st.columns(min(len(indices), 4))
            for i, idx in enumerate(indices[:4]):
                val, yest = idx.get("value"), idx.get("yesterday")
                delta = round(float(val) - float(yest), 2) if val is not None and yest is not None else None
                with icols[i]:
                    metric_card(idx.get("name", f"指数{i}"), f"{val}", delta, " 点", False, "较昨日")

        # 领涨领跌条形图
        ups = sorted([t for t in today if t["hbs"] > 0], key=lambda d: -d["hbs"])[:5]
        downs = sorted([t for t in today if t["hbs"] < 0], key=lambda d: d["hbs"])[:5]
        if ups or downs:
            st.subheader("🚀 今日涨跌榜")
            bc1, bc2 = st.columns(2)
            with bc1:
                if ups:
                    fig_up = px.bar(
                        pd.DataFrame(ups).sort_values("hbs"),
                        x="hbs", y="name", orientation="h",
                        title="领涨 TOP5（红=涨价）",
                        labels={"hbs": "环比%", "name": "品类"},
                        color_discrete_sequence=["#c0392b"],
                    )
                    fig_up.update_layout(height=270, margin=dict(l=10, r=10, t=40, b=10))
                    st.plotly_chart(fig_up, width="stretch")
            with bc2:
                if downs:
                    fig_dn = px.bar(
                        pd.DataFrame(downs).sort_values("hbs", ascending=False),
                        x="hbs", y="name", orientation="h",
                        title="领跌 TOP5（绿=跌价）",
                        labels={"hbs": "环比%", "name": "品类"},
                        color_discrete_sequence=["#1e8449"],
                    )
                    fig_dn.update_layout(height=270, margin=dict(l=10, r=10, t=40, b=10))
                    st.plotly_chart(fig_dn, width="stretch")
    else:
        st.info("未找到当日价格数据，请确认 realtime.json 已上传。")

    # ───────── 模块二：家庭影响 + 画像雷达 ─────────
    if today:
        st.header("💡 你的专属影响测算", divider="green")
        st.markdown(f"按 **{state['members']} 人 / 月收入 ¥{state['income']:,} / "
                    f"{state['region']}·{state['city']} / {persona_badge(state)}** 计算。"
                    f"地区与渠道系数为演示性修正（{price_factor}），非官方统计。")

        rc1, rc2 = st.columns([1, 2])
        with rc1:
            st.plotly_chart(radar_chart(state), width="stretch")
            st.caption("你的饮食画像雷达（数值由上方滑块与选项生成）")
        with rc2:
            show = df_basket.copy()
            show["月支出(元/人)"] = show["月支出"].round(1)
            show["今日影响(元/人·天)"] = show["今日日影响"].round(3)
            total_row = pd.DataFrame([{
                "品类": "合计", "分组": "—", "用量_kg": np.nan, "单价": np.nan,
                "月支出": show["月支出"].sum(), "今日日影响": show["今日日影响"].sum(),
                "月支出(元/人)": show["月支出(元/人)"].sum(),
                "今日影响(元/人·天)": show["今日影响(元/人·天)"].sum(),
            }])
            show = pd.concat([show, total_row], ignore_index=True)
            st.dataframe(
                show[["品类", "分组", "用量_kg", "单价", "月支出(元/人)", "今日影响(元/人·天)"]],
                width="stretch", hide_index=True, height=330,
                column_config={
                    "用量_kg": st.column_config.NumberColumn("用量(kg/月·人)", format="%.2f"),
                    "单价": st.column_config.NumberColumn("单价(元/kg)", format="%.2f"),
                    "月支出(元/人)": st.column_config.NumberColumn("月支出(元/人)", format="%.1f"),
                    "今日影响(元/人·天)": st.column_config.NumberColumn("今日影响(元/人·天)", format="%+.3f"),
                },
            )

        # 省钱挑战
        top_up = sorted([t for t in today if t["hbs"] > 1.5], key=lambda d: -d["hbs"])
        if top_up:
            t = top_up[0]
            alt = _SUBSTITUTES.get(t["name"], "其他平价品类")
            saving = max(0.0, t["price"] * 0.5 * t["hbs"] / 100)
            st.info(f"**💰 省钱挑战：** 今日「{t['name']}」涨幅 +{t['hbs']}% 领跑。"
                    f"若把每人每月 0.5 kg 换成 {alt}，按当前价差估算每天约省 **¥{saving:.3f}**"
                    f"（{state['members']} 人家庭每月约 ¥{saving*state['members']*30:.1f}）。")

        if fam_day_delta >= 0:
            impact = f"今天菜价让你的家庭每天大约**多花 ¥{fam_day_delta:.3f}**（月约 ¥{fam_month_delta:.0f}）。"
        else:
            impact = f"今天菜价让你的家庭每天大约**少花 ¥{abs(fam_day_delta):.3f}**（月约省 ¥{abs(fam_month_delta):.0f}）。"
        if ratio < 0.15:
            verdict = "负担很轻，可以放心吃，偶尔尝尝贵价水果也无妨。"
        elif ratio < 0.3:
            verdict = "负担合理，关注领涨品类、错峰采购就能稳住预算。"
        elif ratio < 0.5:
            verdict = "负担偏高，建议把部分肉类换成鸡蛋/白条鸡，米面油可趁低价囤一点。"
        else:
            verdict = "负担较重，优先保刚需、精简高价品类，并考虑社区团购等渠道。"
        st.success(f"🎯 {impact}\n\n{verdict}")

        # ── 情景压力测试 ──
        st.markdown("#### 🎛️ 价格压力测试（What-if）")
        st.caption("假设未来肉蛋 / 蔬果 / 米面油分别涨跌，实时推演你家菜钱的变化。")
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            meat_shock = st.slider("🥩 肉蛋涨跌 %", -30, 30, 0, 5, key="shock_meat") / 100
        with sc2:
            veg_shock = st.slider("🥬 蔬果涨跌 %", -30, 30, 0, 5, key="shock_veg") / 100
        with sc3:
            staple_shock = st.slider("🍚 米面油涨跌 %", -30, 30, 0, 5, key="shock_staple") / 100

        shock_map = {"肉蛋": meat_shock, "蛋奶": meat_shock, "蔬菜": veg_shock,
                     "水果": veg_shock, "主食": staple_shock}
        base_fam = float(df_basket["月支出"].sum()) * members
        scen = df_basket.copy()
        scen["情景月支出"] = [
            row["月支出"] * (1 + shock_map.get(row["分组"], 0.0))
            for _, row in scen.iterrows()
        ]
        new_fam = float(scen["情景月支出"].sum()) * members
        diff_fam = new_fam - base_fam

        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            metric_card("🧾 基线月菜钱", f"¥{base_fam:,.0f}", None,
                        note="按今日价格推算")
        with pc2:
            metric_card("🔮 情景月菜钱", f"¥{new_fam:,.0f}", diff_fam / 30,
                        " 元/天", False, "较基线每天变化")
        with pc3:
            metric_card("💰 月度差额", f"{'+' if diff_fam >= 0 else ''}¥{diff_fam:,.0f}",
                        diff_fam, " 元/月", False,
                        note="涨价红 / 降价绿")

        grp = scen.groupby("分组").agg(基线=("月支出", "sum"),
                                      情景=("情景月支出", "sum")).reset_index()
        grp["基线"] *= members
        grp["情景"] *= members
        fig_w = go.Figure()
        fig_w.add_trace(go.Bar(name="基线", x=grp["分组"], y=grp["基线"],
                               marker_color="#cbd5e1"))
        fig_w.add_trace(go.Bar(name="情景", x=grp["分组"], y=grp["情景"],
                               marker_color="#2F7A5B"))
        fig_w.update_layout(
            title="各食材组：基线 vs 情景（家庭每月）", height=330,
            barmode="group", margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(orientation="h", y=1.12, x=0), yaxis_title="元/月")
        st.plotly_chart(fig_w, width="stretch")

        if abs(diff_fam) < 0.5:
            st.info("当前滑块都在 0，看到的就是基线。试着拖动一个滑块，看看价格波动如何传导到你的钱包。")
        else:
            lead = grp.assign(变化=grp["情景"] - grp["基线"]).iloc[
                (grp["情景"] - grp["基线"]).abs().argmax()]
            direction = "多花" if diff_fam > 0 else "省下"
            tone = st.warning if diff_fam > 0 else st.success
            tone(f"{'⚠️' if diff_fam > 0 else '✅'} 这个情景下，你家每月将**{direction} "
                 f"¥{abs(diff_fam):,.0f}**（每天约 ¥{abs(diff_fam)/30:.2f}）；"
                 f"影响最大的是「{lead['分组']}」组，变化 {lead['情景']-lead['基线']:+,.0f} 元/月。")

    # ───────── 模块三：采购计划 ─────────
    if today:
        st.header("🥗 家庭食品采购计划", divider="green")
        st.markdown("选个模板，再直接改表格里的品类与用量，实时重算每月菜钱。")

        TEMPLATES = {
            "标准家庭": [("猪肉", 2.5), ("鸡蛋", 1.5), ("白条鸡", 1.0), ("大白菜", 4.0),
                       ("土豆", 3.0), ("西红柿", 2.0), ("黄瓜", 2.0), ("芹菜", 1.5),
                       ("粳米", 6.0), ("豆油", 1.0), ("苹果", 2.0), ("香蕉", 2.0)],
            "有娃家庭": [("猪肉", 2.0), ("鸡蛋", 2.0), ("白条鸡", 1.0), ("大白菜", 4.0),
                       ("土豆", 3.5), ("西红柿", 3.0), ("黄瓜", 2.5), ("苹果", 2.5),
                       ("香蕉", 2.5), ("粳米", 6.5), ("豆油", 1.0)],
            "银发清淡": [("猪肉", 1.2), ("鸡蛋", 1.5), ("白条鸡", 0.8), ("大白菜", 5.0),
                       ("芹菜", 2.0), ("茄子", 2.0), ("土豆", 3.0), ("苹果", 2.0),
                       ("粳米", 5.5), ("豆油", 0.8)],
            "健身增肌": [("猪肉", 4.0), ("鸡蛋", 3.0), ("白条鸡", 2.0), ("牛肉", 2.0),
                       ("大白菜", 4.0), ("西兰花", 3.0), ("香蕉", 3.0), ("粳米", 8.0),
                       ("豆油", 1.0)],
            "独居快手": [("鸡蛋", 1.5), ("白条鸡", 1.0), ("大白菜", 2.0), ("西红柿", 2.0),
                       ("黄瓜", 1.5), ("香蕉", 1.5), ("粳米", 3.0), ("豆油", 0.6)],
            "极简省钱": [("猪肉", 1.2), ("鸡蛋", 1.5), ("大白菜", 5.0), ("土豆", 5.0),
                       ("芹菜", 2.0), ("粳米", 7.0), ("豆油", 1.2)],
        }
        _tpl_names = {n for items in TEMPLATES.values() for n, _ in items}
        opts = sorted({t["name"] for t in today} | _tpl_names)

        tcols = st.columns(3)
        for i, (tname, items) in enumerate(TEMPLATES.items()):
            with tcols[i % 3]:
                if st.button(f"套用「{tname}」", key=f"tpl_{tname}", width="stretch"):
                    st.session_state["food_plan"] = pd.DataFrame(
                        [{"品类": n, "每月用量(公斤)": q} for n, q in items])
                    st.rerun()

        if "food_plan" not in st.session_state or st.session_state["food_plan"] is None:
            st.session_state["food_plan"] = pd.DataFrame(
                [{"品类": n, "每月用量(公斤)": q} for n, q in TEMPLATES["标准家庭"]])

        edited = st.data_editor(
            st.session_state["food_plan"], num_rows="dynamic", key="food_editor",
            column_config={
                "品类": st.column_config.SelectboxColumn("品类", options=opts, width="medium"),
                "每月用量(公斤)": st.column_config.NumberColumn(
                    "每月用量(公斤)", min_value=0.0, step=0.5, width="small"),
            },
            width="stretch", hide_index=True, height=300,
        )
        st.session_state["food_plan"] = edited

        rows, total, ref_count = [], 0.0, 0
        for _, r in edited.iterrows():
            name = str(r["品类"]).strip()
            qty = float(r["每月用量(公斤)"] or 0)
            if not name or qty <= 0:
                continue
            price, src = price_and_src(today, name, _default_price(name))
            price *= price_factor
            if src == "参考":
                ref_count += 1
            cost = price * qty
            total += cost
            rows.append(dict(品类=name, 单价=round(price, 2), 来源=src, 月支出=round(cost, 1)))

        if rows:
            df_plan = pd.DataFrame(rows)
            daily = total / 30
            ratio_plan = total / max(state["income"], 1)
            p1, p2, p3 = st.columns(3)
            with p1:
                metric_card("🧾 计划每月菜钱", f"¥{total:,.0f}", None,
                            note=f"其中 {ref_count} 项为参考价")
            with p2:
                metric_card("📅 折合每天", f"¥{daily:,.1f}", None)
            with p3:
                metric_card("📊 占家庭月收入", f"{ratio_plan*100:.1f}%", None,
                            note=f"{persona_badge(state)} 的预算")

            cL, cR = st.columns([3, 2])
            with cL:
                st.dataframe(df_plan, width="stretch", hide_index=True, height=300)
            with cR:
                fig3 = px.bar(df_plan.sort_values("月支出", ascending=True),
                              x="月支出", y="品类", orientation="h",
                              title="各品类每月花费（横向排行）",
                              color_discrete_sequence=["#2F7A5B"])
                fig3.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig3, width="stretch")
            if ref_count:
                st.caption(f"⚠️ 本计划有 {ref_count}/{len(rows)} 项使用估算参考价"
                           "（今日实时数据缺失），实际以市场为准。")
        else:
            st.info("请在表格里至少添加一行「品类 + 每月用量」，或点上方模板套用。")

    # ───────── 模块四：历史价格走势 ─────────
    st.header("📈 历史价格走势", divider="green")
    st.markdown("选择品类，看长期曲线、30日均线和「现在贵不贵」。历史数据为期货/指数折算价，"
                "与上方批发现价口径不同，请勿直接对比绝对值。")
    labels = {m[2]: m for m in META}
    choice = st.selectbox("选择品类", list(labels.keys()), index=0)
    key, emoji, name, conv = labels[choice]
    df, last, pct, chg30 = load_hist(key, conv)
    if df.empty:
        st.warning(f"未找到 {name} 的历史数据文件 cat_{key}.csv")
    else:
        m1, m2, m3 = st.columns(3)
        with m1:
            metric_card(f"{emoji} 最新价", f"{last} {'元/公斤' if conv != 1 else '点'}", None)
        with m2:
            metric_card("历史分位", f"{pct:.0f}%", None,
                        note="越低越便宜（全历史样本百分位）")
        with m3:
            metric_card("近30日涨跌", f"{chg30:+.1f}%", chg30, "%", False)

        if len(df) > 420:
            step = len(df) // 420
            df_plot = pd.concat([df.iloc[::step], df.iloc[[-1]]])
        else:
            df_plot = df
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["price"],
                                 mode="lines", name="日度价格",
                                 line=dict(color="#2F7A5B", width=1.6)))
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["ma30"],
                                 mode="lines", name="30日均线",
                                 line=dict(color="#E8833A", width=2, dash="dash")))
        fig.add_annotation(x=df_plot["date"].iloc[-1], y=last,
                           text=f"最新 {last}", showarrow=True, arrowhead=2,
                           ax=-40, ay=-25, font=dict(color="#111827"))
        fig.update_layout(title=f"{name} 历史价格走势", height=380,
                          margin=dict(l=20, r=20, t=50, b=20),
                          legend=dict(orientation="h", y=1.12, x=0),
                          yaxis_title="价格(元/公斤)" if conv != 1 else "指数",
                          xaxis_title="日期")
        st.plotly_chart(fig, width="stretch")

    # ───────── 模块六：深度分析实验室 ─────────
    st.header("🔬 深度分析实验室", divider="green")
    st.markdown("同样的数据，换五种问法：**现在贵不贵、什么时候买、风险有多大、谁跟谁一起涨、接下来怎么走**。"
                "以下全部由仓库内历史 CSV 实时计算。")

    labels6 = {m[2]: m for m in META}
    tab_val, tab_sea, tab_risk, tab_corr, tab_fc = st.tabs(
        ["🧭 估值地图", "📅 季节性日历", "🎢 波动风险", "🔗 联动关系", "🔮 趋势预测"])

    with tab_val:
        vm = value_map(allh)
        if not vm.empty:
            fig_vm = go.Figure(go.Bar(
                x=vm["历史分位"], y=vm["品类"], orientation="h",
                marker=dict(color=vm["历史分位"], colorscale="RdYlGn_r", cmin=0, cmax=100,
                            line=dict(color="#ffffff", width=1)),
                text=[f"{v:.0f}%" for v in vm["历史分位"]], textposition="outside",
                hovertemplate="%{y}<br>历史分位 %{x:.1f}%<extra></extra>",
            ))
            fig_vm.add_vline(x=50, line_dash="dash", line_color="#9ca3af")
            fig_vm.update_layout(
                title="当前价在各自历史中的位置（越靠左越便宜）",
                xaxis_title="历史分位 %", height=470,
                margin=dict(l=10, r=50, t=50, b=10))
            st.plotly_chart(fig_vm, width="stretch")
            st.dataframe(
                vm, width="stretch", hide_index=True, height=310,
                column_config={
                    "历史分位": st.column_config.NumberColumn("历史分位%", format="%.1f"),
                    "最新价": st.column_config.NumberColumn("最新价", format="%.2f"),
                    "近一年均价": st.column_config.NumberColumn("近一年均价", format="%.2f"),
                    "偏离均价": st.column_config.NumberColumn("偏离均价%", format="%+.1f"),
                })
            st.caption(f"最便宜：{vm.iloc[0]['品类']}（{vm.iloc[0]['历史分位']:.0f}%）；"
                       f"最贵：{vm.iloc[-1]['品类']}（{vm.iloc[-1]['历史分位']:.0f}%）。"
                       "分位 = 历史样本中低于当前价的比例。历史为期货/指数折算口径，"
                       "与今日批发现价不可直接比绝对值。")

    with tab_sea:
        sm = seasonal_matrix()
        if not sm.empty:
            rel = sm.div(sm.mean(axis=1), axis=0) * 100 - 100
            fig_sea = go.Figure(go.Heatmap(
                z=rel.values, x=list(rel.columns), y=list(rel.index),
                colorscale="RdYlGn_r", zmid=0, colorbar=dict(title="偏离%"),
                hovertemplate="%{y} · %{x}<br>较常年 %{z:+.1f}%<extra></extra>",
            ))
            fig_sea.update_layout(
                title="月度均价相对自身常年水平（绿色 = 便宜窗口）",
                height=520, xaxis_title="月份",
                margin=dict(l=10, r=20, t=50, b=10))
            st.plotly_chart(fig_sea, width="stretch")
            cal = []
            for name, row in sm.iterrows():
                cal.append(dict(品类=name, 最便宜月=str(row.idxmin()),
                                最贵月=str(row.idxmax()),
                                年内价差=round((float(row.max()) / float(row.min()) - 1) * 100, 1)))
            df_cal = pd.DataFrame(cal)
            df_cal["_m"] = df_cal["最便宜月"].str.replace("月", "", regex=False).astype(int)
            df_cal = df_cal.sort_values("_m").drop(columns="_m")
            st.dataframe(df_cal, width="stretch", hide_index=True, height=330)
            st.caption("读法：例如猪肉 12 月均价最低、5 月最高；价差越大，错峰采购越划算。"
                       "季节性由各品类全历史月度均价归集，未剔除长期趋势，仅作课程演示。")

    with tab_risk:
        risks = []
        for name, df in allh.items():
            v, mdd, yoy = risk_metrics(df)
            if np.isfinite(v):
                risks.append(dict(品类=name, 年化波动率=round(v, 1),
                                  最大回撤=round(mdd, 1), 近一年涨跌=round(yoy, 1)))
        df_risk = pd.DataFrame(risks).sort_values("年化波动率", ascending=False)
        if not df_risk.empty:
            fig_risk = px.bar(
                df_risk.sort_values("年化波动率"), x="年化波动率", y="品类", orientation="h",
                color="年化波动率", color_continuous_scale="Reds",
                title="年化波动率排行（越红越不稳）", labels={"年化波动率": "年化波动率 %"})
            fig_risk.update_layout(height=470, margin=dict(l=10, r=20, t=50, b=10))
            st.plotly_chart(fig_risk, width="stretch")
            st.dataframe(df_risk, width="stretch", hide_index=True, height=320)
            stable, wild = df_risk.iloc[-1], df_risk.iloc[0]
            st.caption(f"**{stable['品类']}** 波动最小（{stable['年化波动率']:.0f}%），适合囤；"
                       f"**{wild['品类']}** 波动最大（{wild['年化波动率']:.0f}%），建议少量多次买。"
                       "最大回撤按历史高点到低点计算，不代表未来风险。")

    with tab_corr:
        cm = corr_matrix()
        if cm is not None and cm.shape[0] > 2:
            fig_cm = go.Figure(go.Heatmap(
                z=cm.values, x=list(cm.columns), y=list(cm.index),
                colorscale="RdBu_r", zmin=-1, zmax=1, colorbar=dict(title="r"),
                hovertemplate="%{y} × %{x}<br>r = %{z:.2f}<extra></extra>"))
            fig_cm.update_layout(
                height=580, title="月度收益率相关系数（红=同涨同跌，蓝=反向）",
                margin=dict(l=10, r=20, t=50, b=10))
            st.plotly_chart(fig_cm, width="stretch")
            cols, pairs = list(cm.columns), []
            for i in range(len(cols)):
                for j in range(i + 1, len(cols)):
                    v = cm.iloc[i, j]
                    if pd.notna(v) and np.isfinite(v):
                        pairs.append(dict(品类A=cols[i], 品类B=cols[j],
                                          相关系数=round(float(v), 2)))
            df_pairs = pd.DataFrame(pairs)
            if not df_pairs.empty:
                df_pairs["_a"] = df_pairs["相关系数"].abs()
                df_pairs = df_pairs.sort_values("_a", ascending=False).drop(columns="_a").head(8)
                st.dataframe(df_pairs, width="stretch", hide_index=True, height=300)
            st.caption("Pearson 相关，样本至少 24 个月。油脂类（豆油/棕榈油/菜籽油）同步性高，"
                       "说明它们受同一批原料与政策驱动，互相替代空间有限；强负相关品类则天然可对冲。")

    with tab_fc:
        fc1, fc2 = st.columns([1, 3])
        with fc1:
            fchoice = st.selectbox("选择预测品类", list(labels6.keys()), key="fc_pick")
            st.caption("课程级线性回归外推（最近 120 个交易日 + 噪声区间），"
                       "仅供演示，不构成投资或采购建议。")
        key_f, emo_f, name_f, conv_f = labels6[fchoice]
        fdf, flast, _, _ = load_hist(key_f, conv_f)
        if not fdf.empty and len(fdf) > 60:
            pred, lo, hi, slope, n = forecast_price(fdf, 30)
            fm1, fm2, fm3 = st.columns(3)
            with fm1:
                metric_card(f"{emo_f} 当前价", f"{flast}", None, note="历史序列最新值")
            with fm2:
                metric_card("🔮 30日后预测", f"{pred:.2f}", pred - flast,
                            " 元/公斤" if conv_f != 1 else " 点", False, "线性回归外推")
            with fm3:
                metric_card("📏 95%区间", f"{lo:.2f} ~ {hi:.2f}", None,
                            note=f"基于最近 {n} 个交易日残差")
            recent = fdf.tail(180)
            future_dates = pd.date_range(recent["date"].iloc[-1], periods=31, freq="D")[1:]
            fig_fc = go.Figure()
            fig_fc.add_trace(go.Scatter(x=recent["date"], y=recent["price"],
                                        mode="lines", name="历史价",
                                        line=dict(color="#2F7A5B", width=2)))
            fig_fc.add_trace(go.Scatter(
                x=list(future_dates) + list(future_dates[::-1]),
                y=[hi] * 30 + [lo] * 30, fill="toself",
                fillcolor="rgba(232,131,58,0.16)", line=dict(color="rgba(0,0,0,0)"),
                name="95% 区间", hoverinfo="skip"))
            fig_fc.add_trace(go.Scatter(x=future_dates, y=[pred] * 30,
                                        mode="lines", name="30日预测",
                                        line=dict(color="#E8833A", width=2, dash="dash")))
            fig_fc.add_vline(x=recent["date"].iloc[-1], line_dash="dot", line_color="#9ca3af")
            fig_fc.update_layout(
                title=f"{name_f}：历史 180 天 + 未来 30 天推演", height=420,
                margin=dict(l=20, r=20, t=50, b=20),
                legend=dict(orientation="h", y=1.12, x=0),
                yaxis_title="价格(元/公斤)" if conv_f != 1 else "指数")
            st.plotly_chart(fig_fc, width="stretch")
            trend = "上行" if slope > 0.005 else ("下行" if slope < -0.005 else "横盘")
            st.info(f"📈 模型判断：近 {n} 个交易日呈**{trend}**趋势（日均斜率 {slope:+.4f}）。"
                    f"未来 30 天中心预测 **{pred:.2f}**，区间 **{lo:.2f} ~ {hi:.2f}**。")

    # ───────── 模块五：区域解读 ─────────
    st.header("🗺️ 四大区域菜价解读", divider="green")
    selected_region = state["region"]
    region_df = pd.DataFrame([
        dict(区域=r["name"], 修正系数=REGION_FACTOR[r["name"]]) for r in REGIONS
    ])
    fig_region = px.bar(region_df, x="区域", y="修正系数", color="区域",
                        title="区域价格修正系数（演示估算，非官方统计）",
                        color_discrete_sequence=["#2F7A5B", "#E8833A", "#4A76A8", "#B0555F"])
    fig_region.update_layout(height=280, showlegend=False,
                             margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig_region, width="stretch")
    rcols = st.columns(4)
    for i, r in enumerate(REGIONS):
        with rcols[i]:
            mark = "👈 你在这里" if r["name"] == selected_region else ""
            st.markdown(f"**{r['name']} {mark}**")
            st.caption(r["provs"])
            st.write(r["why"])

    # ───────── 口径与方法 ─────────
    with st.expander("🔍 数据口径与方法（建议展开看看）"):
        st.markdown(f"""
- **今日价格**：农业农村部全国农产品批发市场价格信息系统（pfsc.agri.cn），{fetch_time} 抓取；环比 =（今日价 − 昨日价）/ 昨日价。
- **历史曲线**：期货/指数历史行情折算为元/公斤，与批发现价口径不同，**绝对值不可直接对比**；历史分位 = 当前价在全部历史样本中的百分位；近30日涨跌按样本末 31 个数据点计算。
- **画像修正**：地区 / 城市层级 / 渠道系数为课程演示用估算（当前 {price_factor}），用于展示“同一篮子在不同画像下的差异”，不代表真实市场价格。
- **采购计划**：{_BASE_STATE['income'] if False else len(TEMPLATES)} 套模板可编辑；今日实时价缺失的品类使用参考价，页面会标注数量。
- **局限**：批发价 ≠ 零售价；未计损耗、季节性、个体过敏与真实消费量；结果仅用于数据分析课程演示。
        """)

    st.divider()
    st.caption("数据来源：农业农村部全国农产品批发市场价格信息系统（pfsc.agri.cn）、期货交易所历史行情。"
               "本应用为课程演示用途，价格仅供参考。")


if __name__ == "__main__":
    main()
