"""마크 미너비니(Mark Minervini) SEPA 트렌드 템플릿 국내 주식 스크리너
(SEPA 종합 추천 점수 시스템 & GitHub 무인 자동화 완벽 지원)

마크 미너비니의 '슈퍼 스톡(Superperformance Stocks)' 8대 조건 + SEPA 종합 추천 점수(100점 만점):
1. 주가가 150일(30주), 200일(40주) 이동평균선 위에 위치
2. 150일 이동평균선이 200일 이동평균선 위에 위치
3. 200일 이동평균선이 최소 1개월 이상 지속 상승
4. 50일(10주) 이동평균선이 150일 및 200일 이동평균선 위에 위치 (완전 정배열)
5. 현재 주가가 50일 이동평균선 위에 위치
6. 현재 주가가 52주 신저가 대비 최소 25~30% 이상 상승
7. 현재 주가가 52주 신고가 대비 25% 이내 (10~15% 이내면 초강력 베이스)
8. RS(상대강도) 순위 70 이상 (권장 80 이상)

[SEPA 종합 추천 점수 (100점 만점) 산출 기준]
 - RS 상대강도 모멘텀 (35점): 전체 시장 백분위 순위
 - 신고가 근접성 / 베이스 완성도 (25점): 52주 최고가 대비 괴리율 (0~5% 돌파 임박 최우대)
 - VCP 변동성 축소 패턴 (20점): 20일 변동성 / 60일 변동성 비율 (수축이 심할수록 우대)
 - 이동평균선 정배열 및 200일선 기울기 (10점): 이평선 추세 가속도
 - 거래대금 유동성 (10점): 20일 평균 거래대금 규모 (기관 매수세 유입 가능성)
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import os
import sys
import time
import webbrowser

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from tabulate import tabulate
from tqdm import tqdm

# Windows 콘솔 UTF-8 인코딩 설정
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def format_marcap(val: float | int) -> str:
    """시가총액(원)을 'X조 Y,YYY억원' 또는 'X,YYY억원' 형태로 변환합니다."""
    if pd.isna(val) or val <= 0:
        return "-"
    val = int(val)
    cho = val // 1_000_000_000_000
    eok = (val % 1_000_000_000_000) // 100_000_000
    if cho > 0:
        if eok > 0:
            return f"{cho}조 {eok:,}억"
        return f"{cho}조원"
    return f"{eok:,}억원"


def filter_universe(
    market: str = "ALL", min_price: int = 1000, exclude_bad_dept: bool = True
) -> pd.DataFrame:
    """KRX 상장 종목 중 투자 부적합 종목(스팩, 우선주, ETF, 관리종목 등)을 필터링합니다."""
    print("▶ KRX 전체 종목 목록 수집 및 유니버스 필터링 중...")
    stocks = fdr.StockListing("KRX")

    # 1. 시장 필터 (KOSPI / KOSDAQ / ALL)
    market = market.upper()
    if market == "KOSPI":
        stocks = stocks[stocks["Market"] == "KOSPI"].copy()
    elif market == "KOSDAQ":
        stocks = stocks[stocks["Market"].isin(["KOSDAQ", "KOSDAQ GLOBAL"])].copy()
    else:  # ALL: 코스피 + 코스닥 (코넥스는 제외)
        stocks = stocks[stocks["Market"].isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])].copy()

    # 2. 우선주 제외 (국내 보통주는 일반적으로 종목코드 끝자리가 '0')
    stocks["Code"] = stocks["Code"].astype(str).str.zfill(6)
    stocks = stocks[stocks["Code"].str.endswith("0")].copy()

    # 3. 종목명 기준 제외 (스팩, 리츠, 우선주 표기 등)
    bad_name_keywords = [
        "스팩", "SPAC", "리츠", "1우", "2우", "3우", "우B", "우C",
        "ETN", "ETF", "인버스", "레버리지", "타이거", "코덱스"
    ]
    pattern = "|".join(bad_name_keywords)
    stocks = stocks[~stocks["Name"].str.contains(pattern, case=False, na=False)].copy()

    # 4. 관리종목 / 투자주의환기종목 제외
    if exclude_bad_dept and "Dept" in stocks.columns:
        bad_dept_keywords = ["관리종목", "SPAC", "투자주의환기종목"]
        dept_pattern = "|".join(bad_dept_keywords)
        stocks = stocks[~stocks["Dept"].fillna("").str.contains(dept_pattern, case=False)].copy()

    # 5. 동전주 제외 (현재가 기준)
    if "Close" in stocks.columns and min_price > 0:
        stocks = stocks[pd.to_numeric(stocks["Close"], errors="coerce") >= min_price].copy()

    stocks = stocks.reset_index(drop=True)
    print(f"  ✓ 필터링 완료: 대상 종목 총 {len(stocks):,}개 (스팩/우선주/관리종목/동전주 제외)")
    return stocks


def calculate_stock_metrics(
    code: str, name: str, market: str, marcap: float, start_date: str
) -> dict | None:
    """개별 종목의 주가 데이터를 다운로드하여 트렌드 템플릿 및 RS 계산에 필요한 지표를 산출합니다."""
    try:
        df = fdr.DataReader(code, start=start_date)
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

        # 52주(252거래일) 최고가 / 최저가
        high_52w = float(close.iloc[-252:].max())
        low_52w = float(close.iloc[-252:].min())

        pct_from_52w_high = ((last - high_52w) / high_52w) * 100
        pct_above_52w_low = ((last - low_52w) / low_52w) * 100

        # IBD RS 가중 점수 (3개월 40%, 6개월 20%, 9개월 20%, 12개월 20%)
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


def calculate_sepa_score(row: pd.Series) -> tuple[int, str]:
    """마크 미너비니 SEPA 전략 기반 100점 만점 종합 추천 점수를 계산합니다.
    
    배점:
    1. RS 상대강도 모멘텀 (35점): 전체 시장 상위 백분위 순위
    2. 신고가 근접성 / 베이스 완성도 (25점): 0~5% 이내 돌파 직전 최우선
    3. VCP 변동성 축소 패턴 (20점): 20일 변동성이 60일 변동성 대비 극도로 줄어든 종목
    4. 추세 정배열 및 200일선 가속도 (10점): 장기 추세 우상향 강도
    5. 거래대금 유동성 (10점): 기관 수급 유입 가능 거래대금 규모
    """
    rs = row.get("rs_rating", 50)
    high_dist = row.get("pct_from_52w_high", -25)
    vcp = row.get("vcp_ratio", 1.0)
    ma200_slope = row.get("ma200_slope_pct", 0.0)
    tval = row.get("avg_trading_val_20d", 0.0)

    # 1. RS 점수 (35점 만점)
    if rs >= 95:
        score_rs = 35
    elif rs >= 90:
        score_rs = 31
    elif rs >= 85:
        score_rs = 27
    elif rs >= 80:
        score_rs = 23
    elif rs >= 75:
        score_rs = 19
    else:
        score_rs = 15

    # 2. 신고가 근접도 (25점 만점) - 고점 돌파 직전/베이스 상단 우대
    if high_dist >= -3.0:
        score_high = 25
    elif high_dist >= -7.0:
        score_high = 22
    elif high_dist >= -12.0:
        score_high = 18
    elif high_dist >= -18.0:
        score_high = 13
    else:
        score_high = 8

    # 3. VCP 변동성 축소 (20점 만점) - 수축이 강할수록 피봇 돌파 임박
    if vcp < 0.70:
        score_vcp = 20
    elif vcp < 0.85:
        score_vcp = 17
    elif vcp <= 1.00:
        score_vcp = 13
    elif vcp <= 1.15:
        score_vcp = 8
    else:
        score_vcp = 4

    # 4. 정배열 및 200일선 상승 기울기 (10점 만점)
    score_trend = 5  # 기본 정배열 만족 시 5점
    if ma200_slope >= 3.0:
        score_trend += 5
    elif ma200_slope >= 1.0:
        score_trend += 4
    elif ma200_slope > 0:
        score_trend += 3

    # 5. 거래대금 유동성 (10점 만점)
    if tval >= 500:
        score_vol = 10
    elif tval >= 100:
        score_vol = 9
    elif tval >= 50:
        score_vol = 8
    elif tval >= 20:
        score_vol = 7
    elif tval >= 10:
        score_vol = 6
    else:
        score_vol = 4

    total_score = score_rs + score_high + score_vcp + score_trend + score_vol
    total_score = max(0, min(100, int(total_score)))

    # 등급 부여
    if total_score >= 90:
        grade = "👑 다이아"
    elif total_score >= 80:
        grade = "💎 골드"
    elif total_score >= 70:
        grade = "⭐ 실버"
    else:
        grade = "⚪ 일반"

    return total_score, grade


def run_minervini_screener(
    market: str = "ALL",
    min_rs: int = 70,
    min_trading_val: float = 5.0,
    min_price: int = 1000,
    max_workers: int = 20,
) -> pd.DataFrame:
    """마크 미너비니 트렌드 템플릿 스크리닝 및 SEPA 종합 점수 산출."""
    start_time = time.time()
    today_str = datetime.now().strftime("%Y-%m-%d")
    lookback_date = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")

    market_display = "코스피 + 코스닥 전체" if market.upper() == "ALL" else market
    print("\n" + "=" * 75)
    print(" 🚀 [마크 미너비니 SEPA 트렌드 템플릿 국내 주식 스크리너] 🚀")
    print(f" - 분석 기준일: {today_str}")
    print(f" - 대상 시장: {market_display} | 최소 RS: {min_rs}점 | 최소 거래대금: {min_trading_val}억원")
    print("=" * 75 + "\n")

    universe = filter_universe(market=market, min_price=min_price)
    total_stocks = len(universe)

    print(f"▶ {max_workers}개 스레드로 전 종목 시세 수집 및 기술적 지표 병렬 연산 중...")
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                calculate_stock_metrics,
                row["Code"],
                row["Name"],
                row["Market"],
                row.get("Marcap", 0),
                lookback_date,
            ): row["Code"]
            for _, row in universe.iterrows()
        }

        with tqdm(total=total_stocks, desc="진행률", unit="종목", ncols=80) as pbar:
            for future in as_completed(futures):
                res = future.result()
                if res is not None:
                    results.append(res)
                pbar.update(1)

    elapsed_collect = time.time() - start_time
    print(f"  ✓ {len(results):,}개 종목 분석 완료 (소요 시간: {elapsed_collect:.1f}초)")

    if not results:
        print("❌ 분석 가능한 주식 데이터를 가져오지 못했습니다.")
        return pd.DataFrame()

    df = pd.DataFrame(results)

    # IBD 상대강도(RS Rating, 1~99) 순위 산출
    print("▶ 전체 유니버스 대비 IBD 상대강도(RS Rating, 1~99) 순위 산출 중...")
    df["rs_rating"] = (df["ibd_raw_score"].rank(pct=True) * 99).round().astype(int)
    df["rs_rating"] = df["rs_rating"].clip(lower=1, upper=99)

    # 1차 미너비니 조건 필터링
    passed_mask = (
        df["passed_trend_template"]
        & (df["rs_rating"] >= min_rs)
        & (df["avg_trading_val_20d"] >= min_trading_val)
    )
    screened_df = df[passed_mask].copy()

    if screened_df.empty:
        return screened_df

    # SEPA 종합 추천 점수 (0~100점) 및 추천 등급 산출
    print("▶ 마크 미너비니 SEPA 종합 추천 점수(100점 만점) 및 추천 등급 계산 중...")
    scores_grades = screened_df.apply(calculate_sepa_score, axis=1)
    screened_df["sepa_score"] = [s[0] for s in scores_grades]
    screened_df["sepa_grade"] = [s[1] for s in scores_grades]

    # 정렬: 1순위 SEPA 종합 점수 내림차순, 2순위 RS 순위 내림차순, 3순위 신고가 근접도 내림차순
    screened_df = screened_df.sort_values(
        by=["sepa_score", "rs_rating", "pct_from_52w_high"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    elapsed_total = time.time() - start_time
    print(f"\n🎉 스크리닝 완료! (총 소요 시간: {elapsed_total:.1f}초)")
    print(f"▶ 조건 통과 종목: 총 {len(screened_df):,}개 발견!\n")

    return screened_df


def print_summary_table(df: pd.DataFrame, max_rows: int = 30) -> None:
    """콘솔에 SEPA 종합 점수와 시가총액이 포함된 깔끔한 서식의 표를 출력합니다."""
    if df.empty:
        print("⚠️ 조건을 통과한 종목이 없습니다. 시장이 약세장이거나 기준이 엄격할 수 있습니다.")
        return

    display_df = df.head(max_rows).copy()
    display_df["순위"] = range(1, len(display_df) + 1)
    display_df["종목"] = display_df.apply(lambda r: f"{r['name']} ({r['code']})", axis=1)
    display_df["추천등급"] = display_df["sepa_grade"]
    display_df["종합점수"] = display_df["sepa_score"].apply(lambda x: f"{x}점")
    display_df["시가총액"] = display_df["marcap"].apply(format_marcap)
    display_df["현재가(원)"] = display_df["close"].apply(lambda x: f"{x:,}")
    display_df["RS점수"] = display_df["rs_rating"].apply(lambda x: f"{x}점")
    display_df["52주고점대비"] = display_df["pct_from_52w_high"].apply(lambda x: f"{x:+.1f}%")
    display_df["52주저점대비"] = display_df["pct_above_52w_low"].apply(lambda x: f"+{x:.1f}%")
    display_df["3개월수익률"] = display_df["roc_3m"].apply(lambda x: f"{x:+.1f}%")
    display_df["20일거래대금"] = display_df["avg_trading_val_20d"].apply(lambda x: f"{x:.1f}억")
    display_df["VCP축소"] = display_df["vcp_ratio"].apply(
        lambda x: "🟢 수축" if x < 0.85 else ("🟡 양호" if x <= 1.0 else "⚪ 보통")
    )

    cols = [
        "순위", "종목", "시장", "추천등급", "종합점수", "시가총액", "현재가(원)",
        "RS점수", "52주고점대비", "52주저점대비", "3개월수익률", "20일거래대금", "VCP축소"
    ]
    renamed_df = display_df.rename(columns={"market": "시장"})[cols]

    print("=" * 135)
    print(f" 🏆 마크 미너비니 SEPA 종합 추천 상위 종목 (상위 {len(display_df)}개 표시 / 종합점수 순) 🏆")
    print("=" * 135)
    print(tabulate(renamed_df, headers="keys", tablefmt="simple", showindex=False))
    print("=" * 135)
    if len(df) > max_rows:
        print(f" * 전체 {len(df)}개 종목 중 상위 {max_rows}개만 표시되었습니다. (전체 목록은 CSV/HTML 파일 참조)")


def export_to_csv(df: pd.DataFrame, filename: str | None = None) -> str:
    """결과를 CSV 파일(UTF-8-SIG)로 저장합니다."""
    if filename is None:
        today_str = datetime.now().strftime("%Y%m%d")
        filename = f"minervini_stocks_{today_str}.csv"

    export_df = df.copy()
    export_df["시가총액(요약)"] = export_df["marcap"].apply(format_marcap)

    col_map = {
        "code": "종목코드",
        "name": "종목명",
        "market": "시장",
        "sepa_grade": "SEPA추천등급",
        "sepa_score": "SEPA종합점수(100점만점)",
        "rs_rating": "RS상대강도(1-99)",
        "pct_from_52w_high": "52주신고가괴리율(%)",
        "pct_above_52w_low": "52주신저가대비상승(%)",
        "vcp_ratio": "VCP변동성비율(20d/60d)",
        "시가총액(요약)": "시가총액",
        "marcap": "시가총액(원)",
        "close": "현재가(원)",
        "ma50": "50일이평",
        "ma150": "150일이평",
        "ma200": "200일이평",
        "52w_high": "52주최고가",
        "52w_low": "52주최저가",
        "roc_3m": "3개월수익률(%)",
        "roc_6m": "6개월수익률(%)",
        "roc_12m": "1년수익률(%)",
        "avg_trading_val_20d": "20일평균거래대금(억원)",
    }
    cols_to_keep = [c for c in col_map.keys() if c in export_df.columns]
    export_df = export_df[cols_to_keep].rename(columns=col_map)
    export_df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"📁 CSV 파일 저장 완료: {filename} (엑셀에서 바로 열기 가능)")
    return filename


def export_to_html_dashboard(df: pd.DataFrame, filename: str = "minervini_dashboard.html") -> str:
    """브라우저 및 GitHub Pages에서 열 수 있는 모던 인터랙티브 HTML 대시보드를 생성합니다."""
    today_str = datetime.now().strftime("%Y년 %m월 %d일")

    rows_html = []
    for idx, r in df.iterrows():
        naver_url = f"https://finance.naver.com/item/main.naver?code={r['code']}"

        # 종합점수 뱃지
        score_badge = (
            f'<span class="badge badge-diamond">👑 {r["sepa_score"]}점</span>'
            if r["sepa_score"] >= 90
            else f'<span class="badge badge-gold">💎 {r["sepa_score"]}점</span>'
            if r["sepa_score"] >= 80
            else f'<span class="badge badge-silver">⭐ {r["sepa_score"]}점</span>'
        )

        # RS 뱃지
        rs_badge = (
            f'<span class="badge badge-super">★ {r["rs_rating"]}</span>'
            if r["rs_rating"] >= 90
            else f'<span class="badge badge-high">{r["rs_rating"]}</span>'
            if r["rs_rating"] >= 80
            else f'<span class="badge badge-normal">{r["rs_rating"]}</span>'
        )

        # VCP 뱃지
        vcp_badge = (
            '<span class="badge badge-vcp-good">🟢 수축</span>'
            if r["vcp_ratio"] < 0.85
            else '<span class="badge badge-vcp-normal">🟡 양호</span>'
            if r["vcp_ratio"] <= 1.0
            else '<span class="badge badge-muted">⚪ 보통</span>'
        )

        high_dist_class = "text-danger" if r["pct_from_52w_high"] >= -7 else "text-warning"
        marcap_formatted = format_marcap(r["marcap"])

        row = f"""
        <tr>
            <td class="text-center font-bold">{idx + 1}</td>
            <td>
                <a href="{naver_url}" target="_blank" class="stock-link">
                    <strong>{r['name']}</strong> <small class="text-muted">({r['code']})</small>
                    <span class="external-icon">↗</span>
                </a>
            </td>
            <td class="text-center"><span class="market-tag market-{r['market'].lower().replace(' ', '')}">{r['market']}</span></td>
            <td class="text-center" data-order="{r['sepa_score']}">{score_badge}</td>
            <td class="text-right font-mono font-bold" data-order="{r['marcap']}">{marcap_formatted}</td>
            <td class="text-right font-bold">{r['close']:,}원</td>
            <td class="text-center" data-order="{r['rs_rating']}">{rs_badge}</td>
            <td class="text-right {high_dist_class} font-bold" data-order="{r['pct_from_52w_high']}">{r['pct_from_52w_high']:+.1f}%</td>
            <td class="text-right text-success font-bold" data-order="{r['pct_above_52w_low']}">+{r['pct_above_52w_low']:.1f}%</td>
            <td class="text-right font-mono" data-order="{r['roc_3m']}">{r['roc_3m']:+.1f}%</td>
            <td class="text-right font-mono" data-order="{r['avg_trading_val_20d']}">{r['avg_trading_val_20d']:.1f}억</td>
            <td class="text-center" data-order="{r['vcp_ratio']}">{vcp_badge} <small class="text-muted">({r['vcp_ratio']:.2f})</small></td>
        </tr>
        """
        rows_html.append(row)

    table_body = "\n".join(rows_html)

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>마크 미너비니 SEPA 트렌드 템플릿 추천 대시보드</title>
    <link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
    <style>
        :root {{
            --bg-color: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --text-heading: #f0f6fc;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-gold: #f1e05a;
            --accent-purple: #bc8cff;
        }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1480px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #1f2937, #111827);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }}
        .header h1 {{
            margin: 0 0 8px 0;
            font-size: 26px;
            color: var(--text-heading);
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .header p {{
            margin: 4px 0;
            color: #8b949e;
            font-size: 14px;
            line-height: 1.5;
        }}
        .score-info-box {{
            background: rgba(88, 166, 255, 0.08);
            border: 1px solid rgba(88, 166, 255, 0.3);
            border-radius: 8px;
            padding: 12px 16px;
            margin-top: 14px;
            font-size: 13px;
            color: #c9d1d9;
        }}
        .criteria-box {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 12px;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--border-color);
        }}
        .crit-item {{
            font-size: 13px;
            color: #8b949e;
            background: rgba(255,255,255,0.02);
            padding: 8px 12px;
            border-radius: 6px;
            border-left: 3px solid var(--accent-blue);
        }}
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            overflow-x: auto;
        }}
        table.dataTable {{
            width: 100% !important;
            border-collapse: collapse !important;
            color: var(--text-main);
        }}
        table.dataTable thead th {{
            background-color: #21262d !important;
            color: var(--text-heading) !important;
            border-bottom: 2px solid var(--border-color) !important;
            padding: 12px 10px;
            font-size: 13px;
        }}
        table.dataTable tbody td {{
            padding: 10px 10px;
            border-bottom: 1px solid #21262d;
            font-size: 14px;
        }}
        table.dataTable tbody tr:hover {{
            background-color: rgba(56, 139, 253, 0.08) !important;
        }}
        .stock-link {{
            color: var(--accent-blue);
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            transition: color 0.15s ease;
        }}
        .stock-link:hover {{
            color: #79c0ff;
            text-decoration: underline;
        }}
        .external-icon {{
            font-size: 11px;
            opacity: 0.7;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 9px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 700;
        }}
        .badge-diamond {{
            background: linear-gradient(135deg, rgba(188, 140, 255, 0.3), rgba(88, 166, 255, 0.3));
            color: #e2c5ff;
            border: 1px solid #bc8cff;
        }}
        .badge-gold {{
            background-color: rgba(241, 224, 90, 0.2);
            color: #f1e05a;
            border: 1px solid rgba(241, 224, 90, 0.5);
        }}
        .badge-silver {{
            background-color: rgba(139, 148, 158, 0.2);
            color: #c9d1d9;
            border: 1px solid rgba(139, 148, 158, 0.5);
        }}
        .badge-super {{
            background-color: rgba(241, 224, 90, 0.15);
            color: #f1e05a;
        }}
        .badge-high {{
            background-color: rgba(63, 185, 80, 0.15);
            color: #3fb950;
        }}
        .badge-normal {{
            background-color: rgba(88, 166, 255, 0.15);
            color: #58a6ff;
        }}
        .badge-vcp-good {{
            background-color: rgba(63, 185, 80, 0.15);
            color: #3fb950;
            border: 1px solid rgba(63, 185, 80, 0.3);
        }}
        .badge-vcp-normal {{
            background-color: rgba(210, 153, 34, 0.15);
            color: #d29922;
        }}
        .badge-muted {{
            background-color: rgba(139, 148, 158, 0.15);
            color: #8b949e;
        }}
        .market-tag {{
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 500;
        }}
        .market-kospi {{ background: #233446; color: #79c0ff; }}
        .market-kosdaq {{ background: #3d2a45; color: #d2a8ff; }}
        .market-kosdaqglobal {{ background: #3c3222; color: #e3b341; }}
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .text-danger {{ color: var(--accent-red); }}
        .text-warning {{ color: #e3b341; }}
        .text-success {{ color: var(--accent-green); }}
        .text-muted {{ color: #8b949e; }}
        .font-bold {{ font-weight: 600; }}
        .font-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
        .dataTables_wrapper .dataTables_length,
        .dataTables_wrapper .dataTables_filter,
        .dataTables_wrapper .dataTables_info,
        .dataTables_wrapper .dataTables_paginate {{
            color: #8b949e !important;
            font-size: 13px;
            margin-bottom: 12px;
        }}
        .dataTables_wrapper .dataTables_filter input {{
            background: #21262d;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            color: #fff;
            padding: 6px 10px;
            margin-left: 8px;
        }}
        .dataTables_wrapper .dataTables_paginate .paginate_button {{
            color: #8b949e !important;
            border-radius: 4px !important;
        }}
        .dataTables_wrapper .dataTables_paginate .paginate_button.current {{
            background: #21262d !important;
            border-color: var(--border-color) !important;
            color: #fff !important;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏆 마크 미너비니 SEPA 트렌드 템플릿 추천 대시보드</h1>
            <p>
                <strong>산출 일자:</strong> {today_str} |
                <strong>조건 통과 종목:</strong> <span class="font-bold text-success">{len(df)}개</span> |
                <strong>대상 시장:</strong> 코스피 + 코스닥 전체 |
                <strong>정렬 기준:</strong> SEPA 종합 점수 (100점 만점) 내림차순
            </p>
            <div class="score-info-box">
                🎯 <strong>SEPA 종합 점수(100점 만점) 평가 가중치:</strong>
                상대강도 모멘텀(35점) + 신고가 돌파 근접도(25점) + VCP 변동성 축소 패턴(20점) + 200일선 정배열 가속도(10점) + 거래대금 유동성(10점)
            </div>
            <div class="criteria-box">
                <div class="crit-item">① 주가 > 150일선 및 200일선 위치</div>
                <div class="crit-item">② 150일선 > 200일선 (중장기 정배열)</div>
                <div class="crit-item">③ 200일선 1개월(20일) 전 대비 상승 추세</div>
                <div class="crit-item">④ 50일선 > 150일선 및 200일선 위치</div>
                <div class="crit-item">⑤ 주가 > 50일선 (단기 추세 지지)</div>
                <div class="crit-item">⑥ 52주 최저가 대비 +25% 이상 반등</div>
                <div class="crit-item">⑦ 52주 최고가 대비 -25% 이내 근접</div>
                <div class="crit-item">⑧ IBD 가중 상대강도(RS) 70점 이상</div>
            </div>
        </div>

        <div class="card">
            <table id="screenerTable" class="display nowrap">
                <thead>
                    <tr>
                        <th class="text-center">순위</th>
                        <th>종목명 (코드)</th>
                        <th class="text-center">시장</th>
                        <th class="text-center">SEPA종합점수</th>
                        <th class="text-right">시가총액</th>
                        <th class="text-right">현재가</th>
                        <th class="text-center">RS 상대강도</th>
                        <th class="text-right">52주고점거리</th>
                        <th class="text-right">52주저점상승</th>
                        <th class="text-right">3개월수익</th>
                        <th class="text-right">20일거래대금</th>
                        <th class="text-center">VCP변동성</th>
                    </tr>
                </thead>
                <tbody>
                    {table_body}
                </tbody>
            </table>
        </div>
    </div>

    <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
    <script>
        $(document).ready(function() {{
            $('#screenerTable').DataTable({{
                pageLength: 30,
                order: [[3, 'desc']], // 3번 컬럼(SEPA종합점수) 기본 내림차순 정렬
                language: {{
                    search: "종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: {{
                        first: "처음",
                        last: "마지막",
                        next: "다음",
                        previous: "이전"
                    }}
                }}
            }});
        }});
    </script>
</body>
</html>
"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    # GitHub Pages 호환용 index.html 파일 동시 저장
    try:
        with open("index.html", "w", encoding="utf-8") as f_idx:
            f_idx.write(html_content)
    except Exception:
        pass

    print(f"🌐 인터랙티브 HTML 대시보드 생성 완료: {filename} (GitHub Pages용 index.html 동시 생성)")
    return filename


def interactive_menu() -> tuple[str, int, float, bool]:
    """사용자로부터 실행 옵션을 입력받는 대화형 인터랙티브 메뉴"""
    print("\n" + "=" * 55)
    print("      🎯 마크 미너비니 종목 검색기 설정")
    print("=" * 55)
    print(" [1] 코스피 + 코스닥 전체 (기본값 - 추천)")
    print(" [2] 코스피 (KOSPI)만 검색")
    print(" [3] 코스닥 (KOSDAQ)만 검색")
    market_choice = input("👉 검색할 시장을 선택하세요 [기본값: 1]: ").strip()

    market = "ALL"
    if market_choice == "2":
        market = "KOSPI"
    elif market_choice == "3":
        market = "KOSDAQ"

    rs_input = input("👉 최소 RS 점수를 입력하세요 (1~99, 미너비니 권장: 70~80) [기본값: 70]: ").strip()
    try:
        min_rs = int(rs_input) if rs_input else 70
    except ValueError:
        min_rs = 70

    val_input = input("👉 최소 20일 평균 거래대금(억원) [기본값: 5.0]: ").strip()
    try:
        min_trading_val = float(val_input) if val_input else 5.0
    except ValueError:
        min_trading_val = 5.0

    open_html_input = input("👉 검색 후 브라우저에서 HTML 대시보드를 바로 열까요? (Y/N) [기본값: Y]: ").strip().upper()
    open_html = open_html_input != "N"

    return market, min_rs, min_trading_val, open_html


def main() -> None:
    parser = argparse.ArgumentParser(
        description="마크 미너비니 SEPA 트렌드 템플릿 국내 주식 스크리너"
    )
    parser.add_argument(
        "--market",
        type=str,
        default=None,
        choices=["ALL", "KOSPI", "KOSDAQ"],
        help="검색 시장 (ALL, KOSPI, KOSDAQ)",
    )
    parser.add_argument(
        "--min-rs",
        type=int,
        default=None,
        help="최소 RS 상대강도 점수 (1~99, 기본 70)",
    )
    parser.add_argument(
        "--min-val",
        type=float,
        default=None,
        help="최소 20일 평균 거래대금 (단위: 억원, 기본 5.0)",
    )
    parser.add_argument(
        "--min-price",
        type=int,
        default=1000,
        help="최저 주가 필터 (동전주 제외, 기본 1000원)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=20,
        help="병렬 다운로드 스레드 수 (기본 20)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="스크리닝 완료 후 브라우저 자동 실행 비활성화",
    )

    args = parser.parse_args()

    if args.market is None and args.min_rs is None:
        market, min_rs, min_trading_val, open_html = interactive_menu()
    else:
        market = args.market if args.market else "ALL"
        min_rs = args.min_rs if args.min_rs is not None else 70
        min_trading_val = args.min_val if args.min_val is not None else 5.0
        open_html = not args.no_browser

    screened_df = run_minervini_screener(
        market=market,
        min_rs=min_rs,
        min_trading_val=min_trading_val,
        min_price=args.min_price,
        max_workers=args.workers,
    )

    if not screened_df.empty:
        print_summary_table(screened_df, max_rows=30)
        export_to_csv(screened_df)
        html_file = export_to_html_dashboard(screened_df)

        if open_html:
            try:
                abs_html = os.path.abspath(html_file)
                print(f"👉 브라우저에서 대시보드를 엽니다: {abs_html}")
                webbrowser.open(f"file://{abs_html}")
            except Exception as e:
                print(f"브라우저 실행 중 오류: {e}")

        # 5. GitHub 자동 동기화 (설정 파일이나 토큰이 있으면 자동 실행)
        if os.path.exists("github_config.json") or os.getenv("GITHUB_TOKEN"):
            try:
                from sync_to_github import sync_all_files
                print("\n" + "-" * 60)
                print("▶ GitHub 저장소로 최신 결과 자동 동기화를 진행합니다...")
                sync_all_files()
            except Exception as e:
                print(f"GitHub 자동 동기화 중 오류: {e}")
    else:
        print("\n💡 조건에 맞는 종목이 없습니다. RS 기준을 낮추거나 거래대금 기준을 조정해보세요.")


if __name__ == "__main__":
    main()
