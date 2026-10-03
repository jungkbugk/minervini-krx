"""과거 N개 거래일 동안의 미너비니 SEPA 스크리닝을 소급 적용(Backfill)하여
정확한 '연속 통과 일수(🟢 N일 연속)' 및 '신규 편입(🔥 NEW)', '이탈(🚨 DROP)' 상태를 복원하는 스크립트.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
import os
import sys
import time

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from tqdm import tqdm

from dashboard_generator import generate_unified_dashboard
from history_tracker import track_daily_changes, save_history_log
from minervini_screener import filter_kr_universe, calculate_kr_sepa_score
from minervini_us_screener import fetch_us_universe, calculate_us_sepa_score
from sync_to_github import sync_all_files

# Windows 콘솔 UTF-8 설정
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HISTORY_DIR = "history"


def evaluate_kr_stock_at_date(df: pd.DataFrame, code: str, name: str, market: str, marcap: float, as_of_date: str) -> dict | None:
    """특정 과거 날짜(as_of_date) 시점 기준으로 국내 개별 종목의 지표를 계산합니다."""
    sub = df.loc[:as_of_date]
    if len(sub) < 252:
        return None

    close = sub["Close"].dropna().astype(float)
    volume = sub["Volume"].dropna().astype(float)
    if len(close) < 252:
        return None

    last = float(close.iloc[-1])
    if last <= 0:
        return None

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

    p_63 = float(close.iloc[-63]) if len(close) >= 63 else float(close.iloc[0])
    p_126 = float(close.iloc[-126]) if len(close) >= 126 else float(close.iloc[0])
    p_189 = float(close.iloc[-189]) if len(close) >= 189 else float(close.iloc[0])
    p_252 = float(close.iloc[-252])

    roc_3m = (last - p_63) / p_63 if p_63 > 0 else 0
    roc_6m = (last - p_126) / p_126 if p_126 > 0 else 0
    roc_9m = (last - p_189) / p_189 if p_189 > 0 else 0
    roc_12m = (last - p_252) / p_252 if p_252 > 0 else 0

    ibd_raw = (0.4 * roc_3m) + (0.2 * roc_6m) + (0.2 * roc_9m) + (0.2 * roc_12m)
    recent_val = (close.iloc[-20:] * volume.iloc[-20:]).mean() / 1e8

    high_s = sub["High"].iloc[-60:].astype(float)
    low_s = sub["Low"].iloc[-60:].astype(float)
    close_prev = sub["Close"].iloc[-61:-1].astype(float).values
    tr = np.maximum(
        high_s.values - low_s.values,
        np.maximum(np.abs(high_s.values - close_prev), np.abs(low_s.values - close_prev)),
    )
    atr20 = tr[-20:].mean() / last if last > 0 else 0
    atr60 = tr.mean() / last if last > 0 else 0
    vcp = (atr20 / atr60) if atr60 > 0 else 1.0

    c1 = (last > ma150) and (last > ma200)
    c2 = ma150 > ma200
    c3 = ma200 > ma200_20d_ago
    c4 = (ma50 > ma150) and (ma50 > ma200)
    c5 = last > ma50
    c6 = last >= (low_52w * 1.25)
    c7 = last >= (high_52w * 0.75)
    passed = all([c1, c2, c3, c4, c5, c6, c7])

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
        "ibd_raw_score": ibd_raw,
        "avg_trading_val_20d": round(recent_val, 1),
        "vcp_ratio": round(vcp, 2),
        "passed_trend_template": passed,
    }


def evaluate_us_stock_at_date(df: pd.DataFrame, symbol: str, name: str, exchange: str, marcap: float, as_of_date: str) -> dict | None:
    """특정 과거 날짜(as_of_date) 시점 기준으로 미국 개별 종목의 지표를 계산합니다."""
    sub = df.loc[:as_of_date]
    if len(sub) < 252:
        return None

    close = sub["Close"].dropna().astype(float)
    volume = sub["Volume"].dropna().astype(float)
    if len(close) < 252:
        return None

    last = float(close.iloc[-1])
    if last <= 0:
        return None

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

    p_63 = float(close.iloc[-63]) if len(close) >= 63 else float(close.iloc[0])
    p_126 = float(close.iloc[-126]) if len(close) >= 126 else float(close.iloc[0])
    p_189 = float(close.iloc[-189]) if len(close) >= 189 else float(close.iloc[0])
    p_252 = float(close.iloc[-252])

    roc_3m = (last - p_63) / p_63 if p_63 > 0 else 0
    roc_6m = (last - p_126) / p_126 if p_126 > 0 else 0
    roc_9m = (last - p_189) / p_189 if p_189 > 0 else 0
    roc_12m = (last - p_252) / p_252 if p_252 > 0 else 0

    ibd_raw = (0.4 * roc_3m) + (0.2 * roc_6m) + (0.2 * roc_9m) + (0.2 * roc_12m)
    recent_val = (close.iloc[-20:] * volume.iloc[-20:]).mean()

    high_s = sub["High"].iloc[-60:].astype(float)
    low_s = sub["Low"].iloc[-60:].astype(float)
    close_prev = sub["Close"].iloc[-61:-1].astype(float).values
    tr = np.maximum(
        high_s.values - low_s.values,
        np.maximum(np.abs(high_s.values - close_prev), np.abs(low_s.values - close_prev)),
    )
    atr20 = tr[-20:].mean() / last if last > 0 else 0
    atr60 = tr.mean() / last if last > 0 else 0
    vcp = (atr20 / atr60) if atr60 > 0 else 1.0

    c1 = (last > ma150) and (last > ma200)
    c2 = ma150 > ma200
    c3 = ma200 > ma200_20d_ago
    c4 = (ma50 > ma150) and (ma50 > ma200)
    c5 = last > ma50
    c6 = last >= (low_52w * 1.25)
    c7 = last >= (high_52w * 0.75)
    passed = all([c1, c2, c3, c4, c5, c6, c7])

    return {
        "code": symbol,
        "name": name,
        "market": exchange,
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
        "ibd_raw_score": ibd_raw,
        "avg_trading_val_20d": round(recent_val, 1),
        "vcp_ratio": round(vcp, 2),
        "passed_trend_template": passed,
    }


def backfill_kr(n_days: int = 10, max_workers: int = 30) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    print("\n" + "=" * 75)
    print(f" 🇰🇷 [국내 주식 최근 {n_days}거래일 히스토리 소급 스캔 및 연속 상태 추적]")
    print("=" * 75)

    universe = filter_kr_universe(min_price=1000)
    lookback_date = (datetime.now() - timedelta(days=600)).strftime("%Y-%m-%d")

    print(f"▶ {max_workers}개 스레드로 국내 {len(universe):,}개 전 종목 시세 일괄 수집 중...")
    cache = {}

    def fetch(r):
        code = r["Code"]
        try:
            df = fdr.DataReader(code, start=lookback_date)
            if df is not None and len(df) >= 252:
                return code, (df, r["Name"], r["Market"], r.get("Marcap", 0))
        except Exception:
            pass
        return code, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch, r) for _, r in universe.iterrows()]
        with tqdm(total=len(universe), desc="데이터 수집", unit="종목", ncols=80) as pbar:
            for f in as_completed(futures):
                code, res = f.result()
                if res is not None:
                    cache[code] = res
                pbar.update(1)

    print(f"  ✓ {len(cache):,}개 종목 시세 메모리 캐시 완료!")

    # 기준 거래일 추출 (가장 시세 데이터가 충실한 삼성전자 기준)
    samsung_df = cache.get("005930", (None,))[0]
    if samsung_df is None:
        first_key = list(cache.keys())[0]
        samsung_df = cache[first_key][0]

    all_trading_days = [d.strftime("%Y-%m-%d") for d in samsung_df.index]
    target_dates = all_trading_days[-n_days:]
    print(f"▶ 소급 대상 거래일 ({len(target_dates)}일): {', '.join(target_dates)}\n")

    # 기존 히스토리 로그 초기화 (깨끗한 과거 시점부터 1일씩 누적 재구축)
    save_history_log({"_last_run_date": "", "active_stocks": {}}, "KR")

    last_df = pd.DataFrame()
    last_new = []
    last_drop = []

    for idx, dt in enumerate(target_dates, 1):
        day_results = []
        for code, (df, name, mkt, cap) in cache.items():
            res = evaluate_kr_stock_at_date(df, code, name, mkt, cap, dt)
            if res is not None:
                day_results.append(res)

        day_df = pd.DataFrame(day_results)
        day_df["rs_rating"] = (day_df["ibd_raw_score"].rank(pct=True) * 99).round().astype(int).clip(1, 99)

        passed_mask = (day_df["passed_trend_template"]) & (day_df["rs_rating"] >= 70) & (day_df["avg_trading_val_20d"] >= 5.0)
        screened = day_df[passed_mask].copy()

        if not screened.empty:
            scores_grades = screened.apply(calculate_kr_sepa_score, axis=1)
            screened["sepa_score"] = [s[0] for s in scores_grades]
            screened["sepa_grade"] = [s[1] for s in scores_grades]
            screened = screened.sort_values(
                by=["sepa_score", "rs_rating", "pct_from_52w_high"],
                ascending=[False, False, False]
            ).reset_index(drop=True)

        screened, new_e, dropped = track_daily_changes(screened, dt, market_type="KR")

        # 연속 일수 분포 집계
        days_dist = {}
        for d in screened.get("consecutive_days", []):
            days_dist[d] = days_dist.get(d, 0) + 1
        dist_str = ", ".join([f"{k}일차: {v}개" for k, v in sorted(days_dist.items(), reverse=True)[:4]])

        print(f"  [{idx:2d}/{len(target_dates)}] 📅 {dt} | 통과: {len(screened):2d}개 | 🔥 신규: {len(new_e):2d}개 | 🚨 이탈: {len(dropped):2d}개 | 🟢 {dist_str}")

        last_df = screened
        last_new = new_e
        last_drop = dropped

    # 최신 캐시 저장
    with open(os.path.join(HISTORY_DIR, "latest_kr.json"), "w", encoding="utf-8") as f:
        json.dump({
            "df": last_df.to_dict(orient="records"),
            "new": last_new,
            "drop": last_drop,
            "updated_at": target_dates[-1]
        }, f, ensure_ascii=False, indent=2)

    return last_df, last_new, last_drop


def backfill_us(n_days: int = 10, max_workers: int = 30) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    print("\n" + "=" * 75)
    print(f" 🇺🇸 [미국 주식 최근 {n_days}거래일 히스토리 소급 스캔 및 연속 상태 추적]")
    print("=" * 75)

    universe = fetch_us_universe(min_marcap=300_000_000, min_price=5.0)
    lookback_date = (datetime.now() - timedelta(days=600)).strftime("%Y-%m-%d")

    print(f"▶ {max_workers}개 스레드로 미국 {len(universe):,}개 전 종목 시세 일괄 수집 중...")
    cache = {}

    def fetch(item):
        sym = item["symbol"]
        try:
            df = fdr.DataReader(sym, start=lookback_date)
            if df is not None and len(df) >= 252:
                return sym, (df, item["name"], item["exchange"], item["marcap"])
        except Exception:
            pass
        return sym, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch, item) for item in universe]
        with tqdm(total=len(universe), desc="미국 데이터 수집", unit="종목", ncols=80) as pbar:
            for f in as_completed(futures):
                sym, res = f.result()
                if res is not None:
                    cache[sym] = res
                pbar.update(1)

    print(f"  ✓ {len(cache):,}개 미국 종목 시세 메모리 캐시 완료!")

    # 기준 거래일 추출 (Apple 기준)
    aapl_df = cache.get("AAPL", (None,))[0]
    if aapl_df is None:
        first_key = list(cache.keys())[0]
        aapl_df = cache[first_key][0]

    all_trading_days = [d.strftime("%Y-%m-%d") for d in aapl_df.index]
    target_dates = all_trading_days[-n_days:]
    print(f"▶ 소급 대상 거래일 ({len(target_dates)}일): {', '.join(target_dates)}\n")

    # 기존 히스토리 로그 초기화
    save_history_log({"_last_run_date": "", "active_stocks": {}}, "US")

    last_df = pd.DataFrame()
    last_new = []
    last_drop = []

    for idx, dt in enumerate(target_dates, 1):
        day_results = []
        for sym, (df, name, exch, mcap) in cache.items():
            res = evaluate_us_stock_at_date(df, sym, name, exch, mcap, dt)
            if res is not None:
                day_results.append(res)

        day_df = pd.DataFrame(day_results)
        day_df["rs_rating"] = (day_df["ibd_raw_score"].rank(pct=True) * 99).round().astype(int).clip(1, 99)

        passed_mask = (day_df["passed_trend_template"]) & (day_df["rs_rating"] >= 70)
        screened = day_df[passed_mask].copy()

        if not screened.empty:
            scores_grades = screened.apply(calculate_us_sepa_score, axis=1)
            screened["sepa_score"] = [s[0] for s in scores_grades]
            screened["sepa_grade"] = [s[1] for s in scores_grades]
            screened = screened.sort_values(
                by=["sepa_score", "rs_rating", "pct_from_52w_high"],
                ascending=[False, False, False]
            ).reset_index(drop=True)

        screened, new_e, dropped = track_daily_changes(screened, dt, market_type="US")

        days_dist = {}
        for d in screened.get("consecutive_days", []):
            days_dist[d] = days_dist.get(d, 0) + 1
        dist_str = ", ".join([f"{k}일차: {v}개" for k, v in sorted(days_dist.items(), reverse=True)[:4]])

        print(f"  [{idx:2d}/{len(target_dates)}] 📅 {dt} | 통과: {len(screened):3d}개 | 🔥 신규: {len(new_e):2d}개 | 🚨 이탈: {len(dropped):2d}개 | 🟢 {dist_str}")

        last_df = screened
        last_new = new_e
        last_drop = dropped

    with open(os.path.join(HISTORY_DIR, "latest_us.json"), "w", encoding="utf-8") as f:
        json.dump({
            "df": last_df.to_dict(orient="records"),
            "new": last_new,
            "drop": last_drop,
            "updated_at": target_dates[-1]
        }, f, ensure_ascii=False, indent=2)

    return last_df, last_new, last_drop


def main():
    parser = argparse.ArgumentParser(description="미너비니 SEPA 과거 N거래일 소급 스캔 및 연속 상태 추적")
    parser.add_argument("--market", type=str, default="KR", choices=["KR", "US", "ALL"], help="대상 시장: KR, US, ALL")
    parser.add_argument("--days", type=int, default=10, help="소급할 과거 거래일 수 (기본 10일)")
    parser.add_argument("--workers", type=int, default=30, help="병렬 다운로드 스레드 수 (기본 30)")
    parser.add_argument("--no-sync", action="store_true", help="GitHub 동기화 생략")

    args = parser.parse_args()

    kr_df, kr_new, kr_drop = pd.DataFrame(), [], []
    us_df, us_new, us_drop = pd.DataFrame(), [], []

    # 1. 국내 주식 소급
    if args.market in ["KR", "ALL"]:
        kr_df, kr_new, kr_drop = backfill_kr(n_days=args.days, max_workers=args.workers)
    else:
        with open(os.path.join(HISTORY_DIR, "latest_kr.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
            kr_df, kr_new, kr_drop = pd.DataFrame(d["df"]), d.get("new", []), d.get("drop", [])

    # 2. 미국 주식 소급
    if args.market in ["US", "ALL"]:
        us_df, us_new, us_drop = backfill_us(n_days=args.days, max_workers=args.workers)
    else:
        with open(os.path.join(HISTORY_DIR, "latest_us.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
            us_df, us_new, us_drop = pd.DataFrame(d["df"]), d.get("new", []), d.get("drop", [])

    # 3. 통합 대시보드 갱신
    print("\n▶ 통합 웹 대시보드(index.html)를 갱신합니다...")
    generate_unified_dashboard(
        kr_df=kr_df, us_df=us_df,
        kr_new=kr_new, us_new=us_new,
        kr_drop=kr_drop, us_drop=us_drop,
        output_path="index.html"
    )

    # 4. GitHub 동기화
    if not args.no_sync:
        print("\n▶ 10거래일 히스토리 데이터 및 대시보드를 GitHub에 자동 동기화합니다...")
        sync_all_files()

    print("\n🎉 모든 작업이 완료되었습니다!")


if __name__ == "__main__":
    main()
