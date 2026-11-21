"""마크 미너비니 스크리너 히스토리 추적기 (연속 통과 일수, 신규 편입, 조건 이탈 종목 감지 - 시장별 완전 분리)"""

from __future__ import annotations

import json
import os
import pandas as pd

HISTORY_DIR = "history"


def get_log_file(market_type: str = "KR") -> str:
    m = market_type.lower()
    return os.path.join(HISTORY_DIR, f"history_{m}_log.json")


def load_history_log(market_type: str = "KR") -> dict:
    """누적 히스토리 로그를 시장별로 불러옵니다."""
    log_file = get_log_file(market_type)
    # 기존 단일 파일(history_log.json) 호환
    if not os.path.exists(log_file) and market_type.upper() == "KR":
        legacy_file = os.path.join(HISTORY_DIR, "history_log.json")
        if os.path.exists(legacy_file):
            log_file = legacy_file

    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_history_log(log_data: dict, market_type: str = "KR") -> None:
    """누적 히스토리 로그를 시장별로 저장합니다."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    log_file = get_log_file(market_type)
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)


def track_daily_changes(
    today_df: pd.DataFrame, today_str: str, market_type: str = "KR"
) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """일자별 스크리닝 결과를 비교하여 신규 편입, 이탈 종목, 연속 통과 일수를 계산합니다.
    
    Args:
        today_df: 당일 스크리닝 통과 종목 데이터프레임
        today_str: 'YYYY-MM-DD' 형식 일자
        market_type: 'KR' (국내) 또는 'US' (미국)
        
    Returns:
        (updated_df, new_entrants, dropped_stocks)
    """
    os.makedirs(HISTORY_DIR, exist_ok=True)
    m = market_type.upper()
    history_log = load_history_log(m)

    # 직전 실행 정보 조회
    last_run_date = history_log.get("_last_run_date")
    active_stocks = history_log.get("active_stocks", {})  # {code: {"name": ..., "days": N, ...}}

    current_codes = set(today_df["code"].astype(str).tolist()) if not today_df.empty else set()
    prev_codes = set(active_stocks.keys())

    new_entrants = []
    dropped_stocks = []
    new_active_stocks = {}

    consecutive_days_map = {}
    status_label_map = {}

    # 1. 오늘 통과한 종목 분석 (신규 편입 또는 연속 유지)
    for _, row in today_df.iterrows():
        code = str(row["code"])
        name = str(row["name"])
        sepa_score = row.get("sepa_score", 0)
        close = row.get("close", 0)
        pct_high = row.get("pct_from_52w_high", 0)
        vcp = row.get("vcp_ratio", 1.0)
        marcap = row.get("marcap", 0)

        # 직전에도 있었으면 연속 일수 +1, 아니면 1일차
        if code in active_stocks:
            prev_days = active_stocks[code].get("consecutive_days", 1)
            # 만약 같은 날짜에 재실행된 거면 일수 증가시키지 않음
            days = prev_days if last_run_date == today_str else prev_days + 1
            first_seen = active_stocks[code].get("first_seen", today_str)
            status_label = f"🟢 {days}일 연속"
        else:
            days = 1
            first_seen = today_str
            status_label = "🔥 NEW (1일)"
            new_entrants.append({
                "code": code,
                "name": name,
                "close": close,
                "sepa_score": sepa_score,
                "pct_from_52w_high": pct_high,
                "vcp_ratio": vcp,
                "marcap": marcap,
            })

        new_active_stocks[code] = {
            "name": name,
            "consecutive_days": days,
            "first_seen": first_seen,
            "last_seen": today_str,
            "last_close": close,
            "last_score": sepa_score,
        }
        consecutive_days_map[code] = days
        status_label_map[code] = status_label

    # 2. 직전에 있었으나 오늘 탈락한 종목 (조건 이탈)
    for code in prev_codes - current_codes:
        prev_info = active_stocks[code]
        dropped_stocks.append({
            "code": code,
            "name": prev_info.get("name", code),
            "consecutive_days": prev_info.get("consecutive_days", 1),
            "last_close": prev_info.get("last_close", 0),
            "last_score": prev_info.get("last_score", 0),
        })

    # 3. DataFrame에 일수 및 상태 컬럼 추가
    today_df["consecutive_days"] = today_df["code"].astype(str).map(consecutive_days_map)
    today_df["status_label"] = today_df["code"].astype(str).map(status_label_map)

    # 4. 일자별 CSV 저장 (시장별 분리 보관)
    clean_date = today_str.replace("-", "")
    history_csv = os.path.join(HISTORY_DIR, f"minervini_screened_{m.lower()}_{clean_date}.csv")
    today_df.to_csv(history_csv, index=False, encoding="utf-8-sig")

    # 5. 히스토리 로그 갱신
    history_log["_last_run_date"] = today_str
    history_log["active_stocks"] = new_active_stocks
    save_history_log(history_log, m)

    return today_df, new_entrants, dropped_stocks
