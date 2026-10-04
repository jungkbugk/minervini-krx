"""마크 미너비니(Mark Minervini) SEPA 글로벌 주식 스크리너 (한/미 통합, 일일 리포트·대시보드용)

국내 종목 선별은 실전 매수용 `kr_screener.py` 를 그대로 사용합니다 (유니버스·트렌드 템플릿·RS·점수 규칙을 한 곳에서만 관리).
이 파일은 그 결과에 수급 보조 지표·연속 통과 일수를 붙여 표·대시보드·텔레그램으로 내보냅니다.

사용법:
  - 국내 주식 스크리닝 (기본): python minervini_screener.py --market KR
  - 미국 주식 스크리닝:        python minervini_screener.py --market US
  - 한/미 동시 스크리닝:        python minervini_screener.py --market ALL
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import sys
import time
import webbrowser

import pandas as pd
from tabulate import tabulate

import kr_screener as KS
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(BASE_DIR, "history")

# backfill_history.py 호환용 (규칙은 kr_screener 와 동일)
calculate_kr_sepa_score = KS.calculate_sepa_score


def filter_kr_universe(min_price: int = 1000, min_marcap: int = KS.UNIVERSE_MIN_MARCAP) -> pd.DataFrame:
    return KS.filter_kr_universe(min_price=min_price, min_marcap=min_marcap)


def format_marcap(val: float | int) -> str:
    """시가총액(원)을 억 단위 숫자로 변환합니다."""
    if pd.isna(val) or val <= 0:
        return "-"
    eok = round(float(val) / 100_000_000)
    return f"{eok:,}"


def _to_int(v) -> int:
    try:
        return int(str(v).replace(",", "").replace("+", "") or 0)
    except (TypeError, ValueError):
        return 0


def fetch_kr_investor_flow(codes: list[str]) -> dict[str, dict]:
    """선별 종목의 최근 5일/20일 외인·기관 순매수(억원) 및 외국인 지분율을 병렬 수집합니다. (참고용, 순위에는 쓰지 않음)"""
    import requests

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def fetch_single_flow(code: str) -> dict:
        info = {
            "code": code,
            "foreign_5d": 0.0, "organ_5d": 0.0, "foreign_20d": 0.0, "organ_20d": 0.0,
            "foreign_hold_ratio": "-", "consec_organ_sell": 0,
            "trust_20d": None, "pef_20d": None,      # 투신·사모는 2025년 캐시뿐이라 현재 값이 아님 → 비워 둠
        }
        try:
            r = requests.get(f"https://m.stock.naver.com/api/stock/{code}/trend?page=1&pageSize=20", headers=headers, timeout=5)
            data = r.json() if r.status_code == 200 else None
            if isinstance(data, list) and data:
                def amt(x, key):            # 순매수 수량 × 종가 (원)
                    return _to_int(x.get(key)) * _to_int(x.get("closePrice"))
                info["foreign_5d"] = round(sum(amt(x, "foreignerPureBuyQuant") for x in data[:5]) / 1e8, 1)
                info["organ_5d"] = round(sum(amt(x, "organPureBuyQuant") for x in data[:5]) / 1e8, 1)
                info["foreign_20d"] = round(sum(amt(x, "foreignerPureBuyQuant") for x in data) / 1e8, 1)
                info["organ_20d"] = round(sum(amt(x, "organPureBuyQuant") for x in data) / 1e8, 1)
                info["foreign_hold_ratio"] = data[0].get("foreignerHoldRatio", "-")
                cs = 0
                for x in data:
                    if _to_int(x.get("organPureBuyQuant")) < 0:
                        cs += 1
                    else:
                        break
                info["consec_organ_sell"] = cs
        except Exception:
            pass
        return info

    if not codes:
        return {}
    with ThreadPoolExecutor(max_workers=min(12, len(codes))) as ex:
        return {res["code"]: res for res in ex.map(fetch_single_flow, codes)}


def run_kr_minervini_screener(
    min_rs: int = 70, min_trading_val: float = 5.0, max_workers: int = 20
) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """국내 주식 스크리닝 전체 과정 (선별은 kr_screener, 여기서는 수급·연속 일수 보강)."""
    start_time = time.time()
    today_str = datetime.now().strftime("%Y-%m-%d")

    print("\n" + "=" * 75)
    print(" 🇰🇷 [마크 미너비니 SEPA 트렌드 템플릿 국내 주식 스크리너] 🇰🇷")
    print(f" - 분석 기준일: {today_str} | 최소 RS: {min_rs}점 | 최소 거래대금: {min_trading_val}억원")
    print(f" - 유니버스: 시총 {KS.UNIVERSE_MIN_MARCAP // 100_000_000:,}억 이상 보통주 중 60일 거래대금 상위 {KS.UNIVERSE_TOP_N}종목 (실전 매수용과 동일)")
    print("=" * 75 + "\n")

    cands = KS.run_kr_screening(min_rs=min_rs, min_trading_val=min_trading_val, max_workers=max_workers)
    if not cands:
        return pd.DataFrame(), [], []

    screened_df = pd.DataFrame(cands)

    print("▶ 선별된 주도주의 메이저 수급 동향(외인/기관) 보조 지표 수집 중...")
    flow_map = fetch_kr_investor_flow(screened_df["code"].tolist())
    for col in ["foreign_5d", "organ_5d", "foreign_20d", "organ_20d", "foreign_hold_ratio", "consec_organ_sell", "trust_20d", "pef_20d"]:
        screened_df[col] = screened_df["code"].map(lambda c: flow_map.get(c, {}).get(col))

    screened_df, new_e, dropped = track_daily_changes(screened_df, today_str, market_type="KR")
    print(f"\n🎉 국내 증시 스크리닝 완료! ({time.time() - start_time:.1f}초, 통과: {len(screened_df)}개 | 신규: {len(new_e)}개 | 이탈: {len(dropped)}개)\n")
    return screened_df, new_e, dropped


def print_kr_summary_table(df: pd.DataFrame, max_rows: int = 25) -> None:
    """콘솔에 국내 주식 요약 표를 출력합니다."""
    if df.empty:
        return
    display_df = df.head(max_rows).copy()
    display_df["순위"] = range(1, len(display_df) + 1)
    display_df["종목"] = display_df.apply(lambda r: f"{r['name']} ({r['code']})", axis=1)
    display_df["상태/연속"] = display_df["status_label"]
    display_df["추천등급"] = display_df["sepa_grade"]
    display_df["종합점수"] = display_df["sepa_score"].apply(lambda x: f"{x}점")
    display_df["시총(억)"] = display_df["marcap"].apply(format_marcap)
    display_df["현재가(원)"] = display_df["close"].apply(lambda x: f"{x:,}")
    display_df["RS점수"] = display_df["rs_rating"].apply(lambda x: f"{x}점")
    display_df["52주고점대비"] = display_df["pct_from_52w_high"].apply(lambda x: f"{x:+.1f}%")
    display_df["20일거래대금"] = display_df["avg_trading_val_20d"].apply(lambda x: f"{x:.1f}억")
    display_df["VCP축소"] = display_df["vcp_ratio"].apply(lambda x: "🟢 수축" if x < 0.85 else ("🟡 양호" if x <= 1.0 else "⚪ 보통"))
    display_df["돌파"] = display_df.apply(
        lambda r: f"🚀 {r['vol_surge']:.1f}배" if r.get("breakout20") and r.get("vol_surge", 0) >= 1.5 else ("△ 신고가" if r.get("breakout20") else "-"), axis=1)

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

    renamed = display_df.rename(columns={"market": "시장"})[["순위", "종목", "시장", "상태/연속", "추천등급", "종합점수", "시총(억)", "현재가(원)", "RS점수", "52주고점대비", "20일거래대금", "VCP축소", "돌파", "메이저수급"]]
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
    tmp = f"{cache_file}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cache_file)


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
    os.chdir(BASE_DIR)          # history·index.html 등 상대 경로를 실행 위치와 무관하게 이 폴더 기준으로
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
            print("⚠️ 국내 스캔 결과가 없습니다 (통과 종목 0개 또는 시세·종목 목록 수집 실패). 이전 캐시를 대시보드에 사용합니다.")
            kr_df, kr_new, kr_drop = load_latest_cache("kr")
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
        output_path="minervini_report_local.html"      # 로컬 참고용. 공개 페이지(index.html)는 kr_detail.py 가 관리
    )

    # 5. 브라우저 오픈
    if not args.no_browser:
        try:
            abs_html = os.path.abspath(dashboard_path)
            print(f"👉 브라우저에서 통합 대시보드를 엽니다: {abs_html}")
            webbrowser.open(f"file://{abs_html}")
        except Exception:
            pass

    # 6. GitHub 자동 동기화
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
