"""마크 미너비니(Mark Minervini) SEPA 트렌드 템플릿 미국 주식(US Stocks) 스크리너

미국 시장 특화 필터링:
 - 시장: NASDAQ + NYSE
 - 최소 시가총액: $300M (3억 달러, 미너비니의 초기 슈퍼스톡 발굴 스윗스팟 기준)
 - 최소 주가: $5.0 (페니 스톡/동전주 배제)
 - 스팩(SPAC), ETF, ETN, 워런트/유닛 자동 배제
 - 트레이딩뷰(TradingView) & Finviz 링크 지원
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import os
import sys
import time
import requests

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from tabulate import tabulate
from tqdm import tqdm

from history_tracker import track_daily_changes
from telegram_notifier import send_telegram_alert

# Windows 콘솔 UTF-8 설정
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def format_us_marcap(val: float | int) -> str:
    """시가총액(달러)을 $X.XB(빌리언), $XXXM(밀리언) 형태로 변환합니다."""
    if not val or val <= 0:
        return "-"
    val = float(val)
    if val >= 1e12:
        return f"${val / 1e12:.2f}T"
    elif val >= 1e9:
        return f"${val / 1e9:.2f}B"
    elif val >= 1e6:
        return f"${val / 1e6:.1f}M"
    return f"${val:,.0f}"


def format_us_volume(val: float) -> str:
    """거래대금(달러)을 $XX.XM 형태로 변환합니다."""
    if not val or val <= 0:
        return "-"
    if val >= 1e9:
        return f"${val / 1e9:.1f}B"
    elif val >= 1e6:
        return f"${val / 1e6:.1f}M"
    elif val >= 1e3:
        return f"${val / 1e3:.0f}K"
    return f"${val:,.0f}"


def fetch_us_universe(min_marcap: float = 300_000_000, min_price: float = 5.0) -> list[dict]:
    """네이버 해외증시 API를 통해 NASDAQ 및 NYSE 시총 3억 달러 이상 우량/고성장 유니버스를 빠르게 수집합니다."""
    print("▶ 미국 증시(NASDAQ + NYSE) 시총 3억 달러($300M) 이상 유니버스 수집 중...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    universe = []

    bad_keywords = ["SPAC", "ACQUISITION", "WARRANT", "ETF", "TRUST", "UNITS", "HOLDINGS CORP -"]

    for exchange in ["NASDAQ", "NYSE"]:
        page = 1
        exchange_count = 0
        while True:
            url = f"http://api.stock.naver.com/stock/exchange/{exchange}/marketValue?page={page}&pageSize=60"
            try:
                r = requests.get(url, headers=headers, timeout=10)
                data = r.json()
                items = data.get("stocks", [])
                if not items:
                    break

                for s in items:
                    symbol = s.get("symbolCode", "").strip()
                    name = s.get("stockNameEng", "").strip()
                    mcap = float(s.get("marketValueRaw") or 0)
                    price = float(s.get("closePriceRaw") or 0)
                    industry = s.get("industryCodeType", {}).get("industryGroupKor", "") if s.get("industryCodeType") else ""

                    # 1. 시가총액 미달 시 뒤쪽은 모두 시총이 더 작으므로 조기 탈출
                    if mcap < min_marcap:
                        break

                    # 2. 페니주 제외 ($5 미만)
                    if price < min_price:
                        continue

                    # 3. 스팩, 워런트, 유닛 배제
                    if any(kw in name.upper() for kw in bad_keywords):
                        continue
                    if symbol.endswith(".U") or symbol.endswith(".WS") or len(symbol) > 5:
                        continue

                    universe.append({
                        "symbol": symbol,
                        "name": name,
                        "exchange": exchange,
                        "marcap": mcap,
                        "price": price,
                        "industry": industry,
                    })
                    exchange_count += 1

                # 페이지 마지막 종목이 min_marcap 미만이면 다음 페이지 불필요
                last_mcap = float(items[-1].get("marketValueRaw") or 0)
                if last_mcap < min_marcap or page >= 45:
                    break
                page += 1
            except Exception as e:
                print(f"  ! {exchange} 페이지 {page} 수집 중 오류: {e}")
                break

        print(f"  ✓ {exchange}: {exchange_count:,}개 종목 필터링 완료")

    print(f"  ➔ 총 {len(universe):,}개 미국 주도 유니버스 선정 완료 (최소 시총 $300M & $5 이상)\n")
    return universe


def calculate_us_stock_metrics(item: dict, start_date: str) -> dict | None:
    """개별 미국 종목 시세 데이터를 다운로드하여 트렌드 템플릿 지표를 산출합니다."""
    symbol = item["symbol"]
    name = item["name"]
    exchange = item["exchange"]
    marcap = item["marcap"]

    try:
        df = fdr.DataReader(symbol, start=start_date)
        if df is None or len(df) < 252:
            return None

        close = df["Close"].dropna().astype(float)
        volume = df["Volume"].dropna().astype(float)
        if len(close) < 252:
            return None

        last = float(close.iloc[-1])
        if last <= 0:
            return None

        # 이동평균선
        ma50 = float(close.rolling(50).mean().iloc[-1])
        ma150 = float(close.rolling(150).mean().iloc[-1])
        ma200_series = close.rolling(200).mean()
        ma200 = float(ma200_series.iloc[-1])
        ma200_20d_ago = float(ma200_series.iloc[-21])
        ma200_slope_pct = ((ma200 - ma200_20d_ago) / ma200_20d_ago) * 100 if ma200_20d_ago > 0 else 0

        # 52주 최고가 / 최저가
        high_52w = float(close.iloc[-252:].max())
        low_52w = float(close.iloc[-252:].min())

        pct_from_52w_high = ((last - high_52w) / high_52w) * 100
        pct_above_52w_low = ((last - low_52w) / low_52w) * 100

        # IBD RS 가중치
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

        # 최근 20일 평균 거래대금 ($) 및 거래량 (주)
        avg_volume_20d = float(volume.iloc[-20:].mean())
        avg_trading_val_20d = float((close.iloc[-20:] * volume.iloc[-20:]).mean())

        # 미너비니 유동성 컷: 20일 평균 거래량 10만 주 이상
        if avg_volume_20d < 100_000:
            return None

        # VCP 변동성 축소 패턴 (ATR 20 / ATR 60)
        high_s = df["High"].iloc[-60:].astype(float)
        low_s = df["Low"].iloc[-60:].astype(float)
        close_prev = df["Close"].iloc[-61:-1].astype(float).values
        tr = np.maximum(
            high_s.values - low_s.values,
            np.maximum(
                np.abs(high_s.values - close_prev),
                np.abs(low_s.values - close_prev),
            ),
        )
        atr20 = tr[-20:].mean() / last if last > 0 else 0
        atr60 = tr.mean() / last if last > 0 else 0
        vcp_ratio = (atr20 / atr60) if atr60 > 0 else 1.0

        # 미너비니 8대 조건 검사
        c1 = (last > ma150) and (last > ma200)
        c2 = ma150 > ma200
        c3 = ma200 > ma200_20d_ago
        c4 = (ma50 > ma150) and (ma50 > ma200)
        c5 = last > ma50
        c6 = last >= (low_52w * 1.25)
        c7 = last >= (high_52w * 0.75)

        passed_trend_template = all([c1, c2, c3, c4, c5, c6, c7])

        return {
            "code": symbol,
            "name": name,
            "market": exchange,
            "industry": item.get("industry", ""),
            "marcap": marcap,
            "close": round(last, 2),
            "ma50": round(ma50, 2),
            "ma150": round(ma150, 2),
            "ma200": round(ma200, 2),
            "ma200_slope_pct": round(ma200_slope_pct, 2),
            "52w_high": round(high_52w, 2),
            "52w_low": round(low_52w, 2),
            "pct_from_52w_high": round(pct_from_52w_high, 2),
            "pct_above_52w_low": round(pct_above_52w_low, 2),
            "roc_3m": round(roc_3m * 100, 1),
            "roc_6m": round(roc_6m * 100, 1),
            "roc_12m": round(roc_12m * 100, 1),
            "ibd_raw_score": ibd_raw_score,
            "avg_volume_20d": int(avg_volume_20d),
            "avg_trading_val_20d": round(avg_trading_val_20d, 0),
            "vcp_ratio": round(vcp_ratio, 2),
            "passed_trend_template": passed_trend_template,
        }
    except Exception:
        return None


def calculate_us_sepa_score(row: pd.Series) -> tuple[int, str]:
    """미국 주식 SEPA 종합 추천 점수 (100점 만점) 산출."""
    rs = row.get("rs_rating", 50)
    high_dist = row.get("pct_from_52w_high", -25)
    vcp = row.get("vcp_ratio", 1.0)
    ma200_slope = row.get("ma200_slope_pct", 0.0)
    tval = row.get("avg_trading_val_20d", 0.0)

    # 1. RS 점수 (35점 만점)
    if rs >= 95: score_rs = 35
    elif rs >= 90: score_rs = 31
    elif rs >= 85: score_rs = 27
    elif rs >= 80: score_rs = 23
    elif rs >= 75: score_rs = 19
    else: score_rs = 15

    # 2. 신고가 근접도 (25점 만점)
    if high_dist >= -3.0: score_high = 25
    elif high_dist >= -7.0: score_high = 22
    elif high_dist >= -12.0: score_high = 18
    elif high_dist >= -18.0: score_high = 13
    else: score_high = 8

    # 3. VCP 변동성 축소 (20점 만점)
    if vcp < 0.70: score_vcp = 20
    elif vcp < 0.85: score_vcp = 17
    elif vcp <= 1.00: score_vcp = 13
    elif vcp <= 1.15: score_vcp = 8
    else: score_vcp = 4

    # 4. 200일선 상승 기울기 (10점 만점)
    score_trend = 5
    if ma200_slope >= 3.0: score_trend += 5
    elif ma200_slope >= 1.0: score_trend += 4
    elif ma200_slope > 0: score_trend += 3

    # 5. 거래대금 유동성 (10점 만점) - 미국 주식 기준: $50M+, $20M+, $10M+
    if tval >= 50_000_000: score_vol = 10
    elif tval >= 20_000_000: score_vol = 9
    elif tval >= 10_000_000: score_vol = 8
    elif tval >= 5_000_000: score_vol = 7
    elif tval >= 2_000_000: score_vol = 6
    else: score_vol = 4

    total_score = score_rs + score_high + score_vcp + score_trend + score_vol
    total_score = max(0, min(100, int(total_score)))

    if total_score >= 90: grade = "👑 다이아"
    elif total_score >= 80: grade = "💎 골드"
    elif total_score >= 70: grade = "⭐ 실버"
    else: grade = "⚪ 일반"

    return total_score, grade


def run_us_minervini_screener(
    min_rs: int = 70,
    min_marcap: float = 300_000_000,  # $300M (미너비니 권장 하한선)
    min_price: float = 5.0,
    max_workers: int = 20,
) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """미국 증시 마크 미너비니 스크리닝을 실행합니다."""
    start_time = time.time()
    today_str = datetime.now().strftime("%Y-%m-%d")
    lookback_date = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")

    print("\n" + "=" * 75)
    print(" 🇺🇸 [마크 미너비니 SEPA 트렌드 템플릿 미국 주식 스크리너] 🇺🇸")
    print(f" - 분석 기준일: {today_str}")
    print(f" - 최소 시가총액: ${min_marcap / 1e6:.0f}M ($3억) | 최소 RS: {min_rs}점 | 최소 주가: ${min_price}")
    print("=" * 75 + "\n")

    universe = fetch_us_universe(min_marcap=min_marcap, min_price=min_price)
    total_stocks = len(universe)

    print(f"▶ {max_workers}개 스레드로 미국 전 종목 시세 수집 및 기술적 지표 병렬 연산 중...")
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(calculate_us_stock_metrics, item, lookback_date): item["symbol"]
            for item in universe
        }

        with tqdm(total=total_stocks, desc="진행률", unit="종목", ncols=80) as pbar:
            for future in as_completed(futures):
                res = future.result()
                if res is not None:
                    results.append(res)
                pbar.update(1)

    elapsed_collect = time.time() - start_time
    print(f"  ✓ {len(results):,}개 미국 종목 분석 완료 (소요 시간: {elapsed_collect:.1f}초)")

    if not results:
        print("❌ 분석 가능한 미국 주식 데이터를 가져오지 못했습니다.")
        return pd.DataFrame(), [], []

    df = pd.DataFrame(results)

    # IBD 상대강도 순위 산출
    print("▶ 미국 전체 유니버스 대비 IBD 상대강도(RS Rating, 1~99) 순위 산출 중...")
    df["rs_rating"] = (df["ibd_raw_score"].rank(pct=True) * 99).round().astype(int)
    df["rs_rating"] = df["rs_rating"].clip(lower=1, upper=99)

    passed_mask = df["passed_trend_template"] & (df["rs_rating"] >= min_rs)
    screened_df = df[passed_mask].copy()

    if screened_df.empty:
        return screened_df, [], []

    print("▶ 마크 미너비니 SEPA 종합 추천 점수(100점 만점) 계산 중...")
    scores_grades = screened_df.apply(calculate_us_sepa_score, axis=1)
    screened_df["sepa_score"] = [s[0] for s in scores_grades]
    screened_df["sepa_grade"] = [s[1] for s in scores_grades]

    screened_df = screened_df.sort_values(
        by=["sepa_score", "rs_rating", "pct_from_52w_high"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    # 일자별 히스토리 추적
    history_us_file = "history/history_us_log.json"
    screened_df, new_entrants, dropped_stocks = track_daily_changes(screened_df, today_str)

    elapsed_total = time.time() - start_time
    print(f"\n🎉 미국 증시 스크리닝 완료! (총 소요 시간: {elapsed_total:.1f}초)")
    print(f"▶ 조건 통과 종목: 총 {len(screened_df):,}개 (🔥 신규 편입: {len(new_entrants)}개 | 🚨 조건 이탈: {len(dropped_stocks)}개)\n")

    return screened_df, new_entrants, dropped_stocks


def print_us_summary_table(df: pd.DataFrame, max_rows: int = 30) -> None:
    """콘솔에 미국 주식 표를 출력합니다."""
    if df.empty:
        print("⚠️ 조건을 통과한 미국 종목이 없습니다.")
        return

    display_df = df.head(max_rows).copy()
    display_df["순위"] = range(1, len(display_df) + 1)
    display_df["티커(종목명)"] = display_df.apply(lambda r: f"{r['code']} ({r['name'][:18]})", axis=1)
    display_df["상태/연속"] = display_df["status_label"]
    display_df["추천등급"] = display_df["sepa_grade"]
    display_df["종합점수"] = display_df["sepa_score"].apply(lambda x: f"{x}점")
    display_df["시가총액"] = display_df["marcap"].apply(format_us_marcap)
    display_df["현재가"] = display_df["close"].apply(lambda x: f"${x:,.2f}")
    display_df["RS점수"] = display_df["rs_rating"].apply(lambda x: f"{x}점")
    display_df["52주고점대비"] = display_df["pct_from_52w_high"].apply(lambda x: f"{x:+.1f}%")
    display_df["3개월수익률"] = display_df["roc_3m"].apply(lambda x: f"{x:+.1f}%")
    display_df["20일거래대금"] = display_df["avg_trading_val_20d"].apply(format_us_volume)
    display_df["VCP축소"] = display_df["vcp_ratio"].apply(
        lambda x: "🟢 수축" if x < 0.85 else ("🟡 양호" if x <= 1.0 else "⚪ 보통")
    )

    cols = [
        "순위", "티커(종목명)", "market", "상태/연속", "추천등급", "종합점수",
        "시가총액", "현재가", "RS점수", "52주고점대비", "3개월수익률", "20일거래대금", "VCP축소"
    ]
    renamed_df = display_df.rename(columns={"market": "거래소"})[
        ["순위", "티커(종목명)", "거래소", "상태/연속", "추천등급", "종합점수",
         "시가총액", "현재가", "RS점수", "52주고점대비", "3개월수익률", "20일거래대금", "VCP축소"]
    ]

    print("=" * 145)
    print(f" 🏆 마크 미너비니 SEPA 미국 주식 상위 추천 종목 (상위 {len(display_df)}개 표시) 🏆")
    print("=" * 145)
    print(tabulate(renamed_df, headers="keys", tablefmt="simple", showindex=False))
    print("=" * 145)


if __name__ == "__main__":
    df, new_e, dropped = run_us_minervini_screener(min_rs=70, min_marcap=300_000_000, max_workers=20)
    if not df.empty:
        print_us_summary_table(df, max_rows=30)
        today_str = datetime.now().strftime("%Y%m%d")
        df.to_csv(f"minervini_stocks_us_{today_str}.csv", index=False, encoding="utf-8-sig")
