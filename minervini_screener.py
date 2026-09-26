"""마크 미너비니(Mark Minervini) SEPA 글로벌 주식 스크리너 (한/미 통합)

사용법:
  - 국내 주식 스크리닝 (기본): python minervini_screener.py --market KR
  - 미국 주식 스크리닝:        python minervini_screener.py --market US
  - 한/미 동시 스크리닝:        python minervini_screener.py --market ALL
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
import os
import sys
import time
import webbrowser

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from tabulate import tabulate
from tqdm import tqdm

from dashboard_generator import generate_unified_dashboard
from history_tracker import track_daily_changes
from minervini_us_screener import run_us_minervini_screener, print_us_summary_table
from telegram_notifier import send_telegram_alert

# Windows 콘솔 UTF-8 인코딩 설정
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HISTORY_DIR = "history"


def format_marcap(val: float | int) -> str:
    """시가총액(원)을 'X조 Y,YYY억원' 형태로 변환합니다."""
    if pd.isna(val) or val <= 0: return "-"
    val = int(val)
    cho = val // 1_000_000_000_000
    eok = (val % 1_000_000_000_000) // 100_000_000
    if cho > 0:
        return f"{cho}조 {eok:,}억" if eok > 0 else f"{cho}조"
    return f"{eok:,}억원"


def fetch_kr_stocks_from_naver(min_marcap: int = 500_000_000_000) -> pd.DataFrame:
    """KRX 공시 사이트 접속 장애 시 네이버 증시 API를 통해 시총 5,000억원 이상 종목을 신속하게 수집합니다."""
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    stocks = []
    for mkt in ["KOSPI", "KOSDAQ"]:
        page = 1
        while True:
            try:
                url = f"https://m.stock.naver.com/api/stocks/marketValue/{mkt}?page={page}&pageSize=100"
                r = requests.get(url, headers=headers, timeout=5)
                if r.status_code != 200: break
                items = r.json().get("stocks", [])
                if not items: break
                stop = False
                for item in items:
                    marcap = int(item.get("marketValueRaw") or 0)
                    if marcap < min_marcap:
                        stop = True
                        break
                    stocks.append({
                        "Code": str(item["itemCode"]).zfill(6),
                        "Name": item["stockName"],
                        "Market": mkt,
                        "Marcap": marcap,
                        "Close": int(item.get("closePriceRaw") or 0)
                    })
                if stop or page >= 15:
                    break
                page += 1
            except Exception:
                break
    return pd.DataFrame(stocks)


def filter_kr_universe(min_price: int = 1000, min_marcap: int = 500_000_000_000) -> pd.DataFrame:
    """KRX 상장 종목 중 투자 부적합 종목(스팩, 우선주, ETF, 관리종목 등) 및 시총 5,000억원 미만을 필터링합니다."""
    print("▶ KRX 전체 종목 목록 수집 및 유니버스 필터링 중 (시총 5,000억 이상 대형/중형 주도주)...")
    stocks = None
    try:
        stocks = fdr.StockListing("KRX")
    except Exception as e:
        print(f"  ⚠️ KRX 서버 응답 제한 감지. 고속 네이버 증시 API로 자동 전환합니다...")
        stocks = fetch_kr_stocks_from_naver(min_marcap=min_marcap)

    if stocks is None or stocks.empty:
        stocks = fetch_kr_stocks_from_naver(min_marcap=min_marcap)

    stocks = stocks[stocks["Market"].isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])].copy()

    # 1. 시가총액 5,000억원 이상 필터 (승률 62.7% 고승률 주도주 전략)
    if "Marcap" in stocks.columns and min_marcap > 0:
        stocks = stocks[pd.to_numeric(stocks["Marcap"], errors="coerce") >= min_marcap].copy()

    stocks["Code"] = stocks["Code"].astype(str).str.zfill(6)
    stocks = stocks[stocks["Code"].str.endswith("0")].copy()

    bad_name_keywords = [
        "스팩", "SPAC", "리츠", "1우", "2우", "3우", "우B", "우C",
        "ETN", "ETF", "인버스", "레버리지", "타이거", "코덱스"
    ]
    pattern = "|".join(bad_name_keywords)
    stocks = stocks[~stocks["Name"].str.contains(pattern, case=False, na=False)].copy()

    if "Dept" in stocks.columns:
        bad_dept_keywords = ["관리종목", "SPAC", "투자주의환기종목"]
        dept_pattern = "|".join(bad_dept_keywords)
        stocks = stocks[~stocks["Dept"].fillna("").str.contains(dept_pattern, case=False)].copy()

    if "Close" in stocks.columns and min_price > 0:
        stocks = stocks[pd.to_numeric(stocks["Close"], errors="coerce") >= min_price].copy()

    stocks = stocks.reset_index(drop=True)
    print(f"  ✓ 필터링 완료: 대상 종목 총 {len(stocks):,}개 (시총 5,000억 이상 & 스팩/우선주/관리종목 제외)")
    return stocks


def calculate_kr_stock_metrics(code: str, name: str, market: str, marcap: float, start_date: str) -> dict | None:
    """국내 개별 종목의 지표를 계산합니다."""
    try:
        df = fdr.DataReader(code, start=start_date)
        if df is None or len(df) < 252: return None

        close = df["Close"].dropna().astype(float)
        volume = df["Volume"].dropna().astype(float)
        if len(close) < 252: return None

        last = float(close.iloc[-1])
        if last <= 0: return None

        ma50 = float(close.rolling(50).mean().iloc[-1])
        ma150 = float(close.rolling(150).mean().iloc[-1])
        ma200_series = close.rolling(200).mean()
        ma200 = float(ma200_series.iloc[-1])
        ma200_20d_ago = float(ma200_series.iloc[-21])
        ma200_slope_pct = ((ma200 - ma200_20d_ago) / ma200_20d_ago) * 100 if ma200_20d_ago > 0 else 0

        high_52w = float(close.iloc[-252:].max())
        low_52w = float(close.iloc[-252:].min())

        pct_from_52w_high = ((last - high_52w) / high_52w) * 100
        pct_above_52w_low = ((last - low_52w) / low_52w) * 100

        p_now = last
        p_63 = float(close.iloc[-63]) if len(close) >= 63 else float(close.iloc[0])
        p_126 = float(close.iloc[-126]) if len(close) >= 126 else float(close.iloc[0])
        p_189 = float(close.iloc[-189]) if len(close) >= 189 else float(close.iloc[0])
        p_252 = float(close.iloc[-252])

        roc_3m = (p_now - p_63) / p_63 if p_63 > 0 else 0
        roc_6m = (p_now - p_126) / p_126 if p_126 > 0 else 0
        roc_9m = (p_now - p_189) / p_189 if p_189 > 0 else 0
        roc_12m = (p_now - p_252) / p_252 if p_252 > 0 else 0

        ibd_raw_score = (0.4 * roc_3m) + (0.2 * roc_6m) + (0.2 * roc_9m) + (0.2 * roc_12m)
        recent_trading_val = (close.iloc[-20:] * volume.iloc[-20:]).mean() / 1e8

        high_s = df["High"].iloc[-60:].astype(float)
        low_s = df["Low"].iloc[-60:].astype(float)
        close_prev = df["Close"].iloc[-61:-1].astype(float).values
        tr = np.maximum(
            high_s.values - low_s.values,
            np.maximum(np.abs(high_s.values - close_prev), np.abs(low_s.values - close_prev)),
        )
        atr20 = tr[-20:].mean() / last if last > 0 else 0
        atr60 = tr.mean() / last if last > 0 else 0
        vcp_ratio = (atr20 / atr60) if atr60 > 0 else 1.0

        c1 = (last > ma150) and (last > ma200)
        c2 = ma150 > ma200
        c3 = ma200 > ma200_20d_ago
        c4 = (ma50 > ma150) and (ma50 > ma200)
        c5 = last > ma50
        c6 = last >= (low_52w * 1.25)
        c7 = last >= (high_52w * 0.75)

        passed_trend_template = all([c1, c2, c3, c4, c5, c6, c7])

        return {
            "code": code,
            "name": name,
            "market": market,
            "marcap": int(marcap) if pd.notna(marcap) else 0,
            "close": int(last),
            "ma50": round(ma50, 1),
            "ma150": round(ma150, 1),
            "ma200": round(ma200, 1),
            "ma200_slope_pct": round(ma200_slope_pct, 2),
            "52w_high": int(high_52w),
            "52w_low": int(low_52w),
            "pct_from_52w_high": round(pct_from_52w_high, 2),
            "pct_above_52w_low": round(pct_above_52w_low, 2),
            "roc_3m": round(roc_3m * 100, 1),
            "roc_6m": round(roc_6m * 100, 1),
            "roc_12m": round(roc_12m * 100, 1),
            "ibd_raw_score": ibd_raw_score,
            "avg_trading_val_20d": round(recent_trading_val, 1),
            "vcp_ratio": round(vcp_ratio, 2),
            "passed_trend_template": passed_trend_template,
        }
    except Exception:
        return None


def calculate_kr_sepa_score(row: pd.Series) -> tuple[int, str]:
    """국내 주식 SEPA 종합 추천 점수 (100점 만점) 산출."""
    rs = row.get("rs_rating", 50)
    high_dist = row.get("pct_from_52w_high", -25)
    vcp = row.get("vcp_ratio", 1.0)
    ma200_slope = row.get("ma200_slope_pct", 0.0)
    tval = row.get("avg_trading_val_20d", 0.0)

    if rs >= 95: score_rs = 35
    elif rs >= 90: score_rs = 31
    elif rs >= 85: score_rs = 27
    elif rs >= 80: score_rs = 23
    elif rs >= 75: score_rs = 19
    else: score_rs = 15

    if high_dist >= -3.0: score_high = 25
    elif high_dist >= -7.0: score_high = 22
    elif high_dist >= -12.0: score_high = 18
    elif high_dist >= -18.0: score_high = 13
    else: score_high = 8

    if vcp < 0.70: score_vcp = 20
    elif vcp < 0.85: score_vcp = 17
    elif vcp <= 1.00: score_vcp = 13
    elif vcp <= 1.15: score_vcp = 8
    else: score_vcp = 4

    score_trend = 5
    if ma200_slope >= 3.0: score_trend += 5
    elif ma200_slope >= 1.0: score_trend += 4
    elif ma200_slope > 0: score_trend += 3

    if tval >= 500: score_vol = 10
    elif tval >= 100: score_vol = 9
    elif tval >= 50: score_vol = 8
    elif tval >= 20: score_vol = 7
    elif tval >= 10: score_vol = 6
    else: score_vol = 4

    total_score = max(0, min(100, int(score_rs + score_high + score_vcp + score_trend + score_vol)))
    if total_score >= 90: grade = "👑 다이아"
    elif total_score >= 80: grade = "💎 골드"
    elif total_score >= 70: grade = "⭐ 실버"
    else: grade = "⚪ 일반"

    return total_score, grade


def fetch_kr_investor_flow(codes: list[str]) -> dict[str, dict]:
    """국내 선별 종목들의 최근 5일/20일 외인/기관 수급 및 지분율을 병렬 수집합니다."""
    import requests
    import pickle

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # 투신/사모 세부 캐시 로드 (있을 경우)
    detailed_cache = {}
    detailed_path = os.path.join(HISTORY_DIR, "detailed_investor_cache_2025.pkl")
    if os.path.exists(detailed_path):
        try:
            with open(detailed_path, "rb") as f:
                detailed_cache = pickle.load(f)
        except Exception:
            detailed_cache = {}

    def fetch_single_flow(code: str) -> dict:
        info = {
            "code": code,
            "foreign_5d": 0.0,
            "organ_5d": 0.0,
            "foreign_20d": 0.0,
            "organ_20d": 0.0,
            "foreign_hold_ratio": "-",
            "consec_organ_sell": 0,
            "trust_20d": None,
            "pef_20d": None,
        }
        try:
            url = f"https://m.stock.naver.com/api/stock/{code}/trend?page=1&pageSize=20"
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    f_5d = sum(int(x.get("foreignerPureBuyQuant", "0").replace(",", "")) * int(x.get("closePrice", "0").replace(",", "")) for x in data[:5]) / 1e8
                    o_5d = sum(int(x.get("organPureBuyQuant", "0").replace(",", "")) * int(x.get("closePrice", "0").replace(",", "")) for x in data[:5]) / 1e8
                    f_20d = sum(int(x.get("foreignerPureBuyQuant", "0").replace(",", "")) * int(x.get("closePrice", "0").replace(",", "")) for x in data) / 1e8
                    o_20d = sum(int(x.get("organPureBuyQuant", "0").replace(",", "")) * int(x.get("closePrice", "0").replace(",", "")) for x in data) / 1e8
                    hold_ratio = data[0].get("foreignerHoldRatio", "-")

                    consec_sell = 0
                    for x in data:
                        if int(x.get("organPureBuyQuant", "0").replace(",", "")) < 0:
                            consec_sell += 1
                        else:
                            break

                    info["foreign_5d"] = round(f_5d, 1)
                    info["organ_5d"] = round(o_5d, 1)
                    info["foreign_20d"] = round(f_20d, 1)
                    info["organ_20d"] = round(o_20d, 1)
                    info["foreign_hold_ratio"] = hold_ratio
                    info["consec_organ_sell"] = consec_sell
        except Exception:
            pass

        # 투신/사모 세부 데이터 확인
        if code in detailed_cache:
            df_c = detailed_cache[code]
            if df_c is not None and not df_c.empty:
                t_sum = round(float(df_c["투신"].iloc[-20:].sum() / 1e8), 1) if "투신" in df_c.columns else 0.0
                p_sum = round(float(df_c["사모"].iloc[-20:].sum() / 1e8), 1) if "사모" in df_c.columns else 0.0
                info["trust_20d"] = t_sum
                info["pef_20d"] = p_sum

        return info

    flow_map = {}
    with ThreadPoolExecutor(max_workers=min(12, len(codes) or 1)) as ex:
        results = list(ex.map(fetch_single_flow, codes))
        for res in results:
            flow_map[res["code"]] = res
    return flow_map


def run_kr_minervini_screener(
    min_rs: int = 70, min_trading_val: float = 5.0, min_price: int = 1000, max_workers: int = 20
) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """국내 주식 스크리닝 전체 과정."""
    start_time = time.time()
    today_str = datetime.now().strftime("%Y-%m-%d")
    lookback_date = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")

    print("\n" + "=" * 75)
    print(" 🇰🇷 [마크 미너비니 SEPA 트렌드 템플릿 국내 주식 스크리너] 🇰🇷")
    print(f" - 분석 기준일: {today_str} | 최소 RS: {min_rs}점 | 최소 거래대금: {min_trading_val}억원")
    print("=" * 75 + "\n")

    universe = filter_kr_universe(min_price=min_price)
    total_stocks = len(universe)

    print(f"▶ {max_workers}개 스레드로 국내 전 종목 시세 수집 및 기술적 지표 병렬 연산 중...")
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(calculate_kr_stock_metrics, r["Code"], r["Name"], r["Market"], r.get("Marcap", 0), lookback_date): r["Code"]
            for _, r in universe.iterrows()
        }
        with tqdm(total=total_stocks, desc="진행률", unit="종목", ncols=80) as pbar:
            for f in as_completed(futures):
                res = f.result()
                if res is not None: results.append(res)
                pbar.update(1)

    if not results: return pd.DataFrame(), [], []

    df = pd.DataFrame(results)
    df["rs_rating"] = (df["ibd_raw_score"].rank(pct=True) * 99).round().astype(int).clip(1, 99)
    passed_mask = df["passed_trend_template"] & (df["rs_rating"] >= min_rs) & (df["avg_trading_val_20d"] >= min_trading_val)
    screened_df = df[passed_mask].copy()

    if screened_df.empty: return screened_df, [], []

    scores_grades = screened_df.apply(calculate_kr_sepa_score, axis=1)
    screened_df["sepa_score"] = [s[0] for s in scores_grades]
    screened_df["sepa_grade"] = [s[1] for s in scores_grades]
    screened_df = screened_df.sort_values(by=["sepa_score", "rs_rating", "pct_from_52w_high"], ascending=[False, False, False]).reset_index(drop=True)

    # 통과된 상위 종목들의 수급(외인/기관/투신/사모) 보조 정보 수집 (순위는 고승률 VCP 기준 그대로 유지)
    print("▶ 선별된 주도주의 메이저 수급 동향(외인/기관/투신/사모) 보조 지표 수집 중...")
    flow_map = fetch_kr_investor_flow(screened_df["code"].tolist())
    for col in ["foreign_5d", "organ_5d", "foreign_20d", "organ_20d", "foreign_hold_ratio", "consec_organ_sell", "trust_20d", "pef_20d"]:
        screened_df[col] = screened_df["code"].map(lambda c: flow_map.get(c, {}).get(col))

    screened_df, new_e, dropped = track_daily_changes(screened_df, today_str, market_type="KR")
    print(f"\n🎉 국내 증시 스크리닝 완료! ({time.time() - start_time:.1f}초, 통과: {len(screened_df)}개 | 신규: {len(new_e)}개 | 이탈: {len(dropped)}개)\n")
    return screened_df, new_e, dropped


def print_kr_summary_table(df: pd.DataFrame, max_rows: int = 25) -> None:
    """콘솔에 국내 주식 요약 표를 출력합니다."""
    if df.empty: return
    display_df = df.head(max_rows).copy()
    display_df["순위"] = range(1, len(display_df) + 1)
    display_df["종목"] = display_df.apply(lambda r: f"{r['name']} ({r['code']})", axis=1)
    display_df["상태/연속"] = display_df["status_label"]
    display_df["추천등급"] = display_df["sepa_grade"]
    display_df["종합점수"] = display_df["sepa_score"].apply(lambda x: f"{x}점")
    display_df["시가총액"] = display_df["marcap"].apply(format_marcap)
    display_df["현재가(원)"] = display_df["close"].apply(lambda x: f"{x:,}")
    display_df["RS점수"] = display_df["rs_rating"].apply(lambda x: f"{x}점")
    display_df["52주고점대비"] = display_df["pct_from_52w_high"].apply(lambda x: f"{x:+.1f}%")
    display_df["20일거래대금"] = display_df["avg_trading_val_20d"].apply(lambda x: f"{x:.1f}억")
    display_df["VCP축소"] = display_df["vcp_ratio"].apply(lambda x: "🟢 수축" if x < 0.85 else ("🟡 양호" if x <= 1.0 else "⚪ 보통"))

    def format_flow_label(r):
        f5 = float(r.get("foreign_5d") or 0)
        o5 = float(r.get("organ_5d") or 0)
        cs = int(r.get("consec_organ_sell") or 0)
        if f5 > 0 and o5 > 0: return "🔥 쌍끌이"
        elif o5 > 0: return "🟢 기관매수"
        elif f5 > 0: return "🔵 외인매수"
        elif cs >= 3: return f"⚠️ 기관{cs}일매도"
        elif o5 < 0 and f5 < 0: return "⚪ 개인매수"
        return "⚪ 관망"

    display_df["메이저수급"] = display_df.apply(format_flow_label, axis=1)

    cols = ["순위", "종목", "market", "상태/연속", "추천등급", "종합점수", "시가총액", "현재가(원)", "RS점수", "52주고점대비", "20일거래대금", "VCP축소", "메이저수급"]
    renamed = display_df.rename(columns={"market": "시장"})[["순위", "종목", "시장", "상태/연속", "추천등급", "종합점수", "시가총액", "현재가(원)", "RS점수", "52주고점대비", "20일거래대금", "VCP축소", "메이저수급"]]
    print("=" * 150)
    print(f" 🏆 마크 미너비니 SEPA 국내 주식 상위 추천 종목 (상위 {len(display_df)}개 표시) 🏆")
    print("=" * 150)
    print(tabulate(renamed, headers="keys", tablefmt="simple", showindex=False))
    print("=" * 150)


def save_latest_cache(market_type: str, df: pd.DataFrame, new_e: list, drop: list) -> None:
    """통합 대시보드 렌더링을 위해 각 시장별 최신 결과를 캐시 파일로 보관합니다."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    cache_file = os.path.join(HISTORY_DIR, f"latest_{market_type.lower()}.json")
    data = {
        "df": df.to_dict(orient="records"),
        "new": new_e,
        "drop": drop,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_latest_cache(market_type: str) -> tuple[pd.DataFrame, list, list]:
    """저장된 최신 캐시를 불러옵니다."""
    cache_file = os.path.join(HISTORY_DIR, f"latest_{market_type.lower()}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return pd.DataFrame(data.get("df", [])), data.get("new", []), data.get("drop", [])
        except Exception:
            pass
    return pd.DataFrame(), [], []


def main() -> None:
    parser = argparse.ArgumentParser(description="마크 미너비니 SEPA 글로벌 주식 스크리너 (한/미 통합)")
    parser.add_argument("--market", type=str, default="KR", choices=["KR", "US", "ALL"], help="대상 시장: KR(국내), US(미국), ALL(전체)")
    parser.add_argument("--min-rs", type=int, default=70, help="최소 RS 상대강도 점수 (기본 70)")
    parser.add_argument("--min-cap", type=float, default=300_000_000, help="미국 주식 최소 시가총액 (기본 $300M = 3억 달러)")
    parser.add_argument("--min-val", type=float, default=5.0, help="미국 주식 최소 주가 (기본 $5.0 이상)")
    parser.add_argument("--workers", type=int, default=20, help="병렬 다운로드 스레드 수")
    parser.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 끄기")

    args = parser.parse_args()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 0. 시장 레짐(Market Regime 50MA) 필터 진단
    try:
        from market_filter import get_market_regime
        regime = get_market_regime(force_refresh=True)
        kr_reg = regime.get("kr", {})
        us_reg = regime.get("us", {})
        print("\n" + "=" * 110)
        print(" 🛡️ [마크 미너비니 시장 레짐 필터 (50일 이동평균선 감시)]")
        print(f" • 🇰🇷 국내 증시 (KOSPI/KOSDAQ): {kr_reg.get('action', '')}")
        print(f"   👉 행동 수칙: {kr_reg.get('message', '')}")
        print(f" • 🇺🇸 미국 증시 (NASDAQ/SP500): {us_reg.get('action', '')}")
        print(f"   👉 행동 수칙: {us_reg.get('message', '')}")
        print("=" * 110 + "\n")
    except Exception as e:
        print(f"시장 레짐 진단 중 참고 오류: {e}")

    kr_df, kr_new, kr_drop = pd.DataFrame(), [], []
    us_df, us_new, us_drop = pd.DataFrame(), [], []

    # 1. 국내 주식 스캔
    if args.market in ["KR", "ALL"]:
        kr_df, kr_new, kr_drop = run_kr_minervini_screener(min_rs=args.min_rs, max_workers=args.workers)
        if not kr_df.empty:
            print_kr_summary_table(kr_df, max_rows=25)
            save_latest_cache("kr", kr_df, kr_new, kr_drop)
            send_telegram_alert(today_str, len(kr_df), kr_df.to_dict(orient="records"), kr_new, kr_drop, market_name="국내 주식")
    else:
        kr_df, kr_new, kr_drop = load_latest_cache("kr")

    # 2. 미국 주식 스캔
    if args.market in ["US", "ALL"]:
        us_df, us_new, us_drop = run_us_minervini_screener(min_rs=args.min_rs, min_marcap=args.min_cap, min_price=args.min_val, max_workers=args.workers)
        if not us_df.empty:
            print_us_summary_table(us_df, max_rows=25)
            save_latest_cache("us", us_df, us_new, us_drop)
            send_telegram_alert(today_str, len(us_df), us_df.to_dict(orient="records"), us_new, us_drop, market_name="미국 주식")
    else:
        us_df, us_new, us_drop = load_latest_cache("us")

    # 3. 보유 종목 미너비니 매도 시점 감시
    sell_signals = []
    try:
        from minervini_sell_monitor import run_sell_monitor
        sell_signals = run_sell_monitor()
    except Exception as e:
        print(f"매도 감시 실행 중 오류: {e}")

    # 4. 한/미 스크리너 및 매도 감시 통합 대시보드 (index.html) 생성
    dashboard_path = generate_unified_dashboard(
        kr_df=kr_df, us_df=us_df,
        kr_new=kr_new, us_new=us_new,
        kr_drop=kr_drop, us_drop=us_drop,
        sell_signals=sell_signals,
        output_path="index.html"
    )

    # 4. 브라우저 오픈
    if not args.no_browser:
        try:
            abs_html = os.path.abspath(dashboard_path)
            print(f"👉 브라우저에서 통합 대시보드를 엽니다: {abs_html}")
            webbrowser.open(f"file://{abs_html}")
        except Exception:
            pass

    # 5. GitHub 자동 동기화
    if os.path.exists("github_config.json") or os.getenv("GITHUB_TOKEN"):
        try:
            from sync_to_github import sync_all_files
            print("\n" + "-" * 60)
            print("▶ GitHub 저장소로 통합 대시보드 자동 동기화를 진행합니다...")
            sync_all_files()
        except Exception as e:
            print(f"GitHub 자동 동기화 중 오류: {e}")


if __name__ == "__main__":
    main()
