"""마크 미너비니 SEPA 매도 원칙 기반 보유 종목 감시 엔진 (Sell Monitor)

[마크 미너비니 6대 핵심 매도 규칙 적용]
1. 🚨 긴급 손절 (Initial Hard Stop): 매수가 대비 -7% ~ -8% 도달 시 기계적 손절
2. 🛡️ 본전 보호 (Break-Even Stop): 매수 후 +12% 이상 상승했던 종목이 매수가로 반락 시 본전 청산
3. 🎯 트레일링 익절 (Trailing Profit Stop): +20% 이상 큰 수익 후 최고가 대비 -10% 이상 하락 시 전량 익절
4. ⚡ 클라이맥스 고점 (Sell into Strength): 200일선 70%+ 과이격 및 수직 급등 시 1/2 분할 익절
5. ⚠️ 50일선 대량거래 붕괴 (50MA Violation): 기관 수급 지지선인 50일선 이탈 시 매도
6. 🟢 추세 순항 (Strong Hold): 주요 지지선 유지 중인 경우 지속 보유
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
import sys

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from tabulate import tabulate

from portfolio_manager import load_portfolio, save_portfolio
from telegram_notifier import load_telegram_config

# Windows 콘솔 UTF-8 설정
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HISTORY_DIR = "history"
SIGNALS_FILE = os.path.join(HISTORY_DIR, "latest_sell_signals.json")


def analyze_single_position(pos: dict) -> dict | None:
    """단일 보유 종목의 미너비니 매도 시점 지표를 정밀 분석합니다."""
    code = str(pos["code"]).strip().upper()
    name = pos.get("name", code)
    market = pos.get("market", "KR").upper()
    buy_price = float(pos.get("buy_price", 0))
    buy_date = pos.get("buy_date", "")

    if buy_price <= 0:
        return None

    # 시세 데이터 수집 (50/150/200 이평 계산을 위해 매수일 이전 350일치 포함)
    lookback_start = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")

    try:
        df = fdr.DataReader(code, start=lookback_start)
        if df is None or len(df) < 50:
            return None

        close = df["Close"].dropna().astype(float)
        volume = df["Volume"].dropna().astype(float)
        high = df["High"].dropna().astype(float)
        low = df["Low"].dropna().astype(float)

        current_price = float(close.iloc[-1])
        current_vol = float(volume.iloc[-1])
        avg_vol_20d = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else current_vol

        # 이동평균선
        ma20 = float(close.rolling(20).mean().iloc[-1])
        ma50 = float(close.rolling(50).mean().iloc[-1])
        ma150 = float(close.rolling(150).mean().iloc[-1])
        ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else ma150

        # 매수일 이후 시세 추적
        if buy_date and buy_date in df.index:
            since_buy = df.loc[buy_date:]
        else:
            # 매수일이 없거나 공휴일이면 가장 근접한 날부터
            since_buy = df.tail(60)

        peak_price = float(since_buy["High"].max()) if not since_buy.empty else current_price
        peak_idx = since_buy["High"].idxmax() if not since_buy.empty else df.index[-1]
        peak_date = peak_idx.strftime("%Y-%m-%d") if hasattr(peak_idx, "strftime") else str(peak_idx)[:10]

        # 손익률 계산
        current_return_pct = ((current_price - buy_price) / buy_price) * 100
        max_return_pct = ((peak_price - buy_price) / buy_price) * 100
        pct_from_peak = ((current_price - peak_price) / peak_price) * 100

        # ----------------------------------------------------
        # 마크 미너비니 6대 매도 룰 평가
        # ----------------------------------------------------
        # 1. 초기 하드 손절선 (-7.5%)
        initial_stop_price = buy_price * 0.925

        # 2. 고점 대비 트레일링 익절선 (-10%)
        trailing_stop_price = peak_price * 0.90

        # 활성 스탑로스 결정
        if max_return_pct >= 15.0:
            # 15% 이상 수익이 났던 종목은 스탑을 최소 본전으로 올림
            active_stop_price = max(buy_price * 1.01, trailing_stop_price)
        else:
            active_stop_price = initial_stop_price

        signal = "🟢 홀딩 (추세 순항)"
        urgency = "SAFE"
        action_plan = "정상 상승 추세 유지 중. 손절선 유지하며 홀딩."

        # Rule 1: 절대 손절 (-7.5% 도달)
        if current_return_pct <= -7.5:
            signal = "🚨 긴급 손절 (Stop-Loss)"
            urgency = "CRITICAL"
            action_plan = f"손실 -7~8% 제한 원칙. 현재 {current_return_pct:.1f}% 손실이므로 무조건 전량 손절."

        # Rule 2: 50일선 거래량 실린 붕괴
        elif current_price < ma50 and (current_vol >= avg_vol_20d * 1.3 or close.iloc[-2] < ma50):
            signal = "⚠️ 50일선 이탈 매도"
            urgency = "WARNING"
            action_plan = "기관 수급 생명선인 50일선 거래량 실린 이탈. 보유 물량 전량 청산 또는 1/2 이상 축소."

        # Rule 3: 트레일링 익절 (+20% 이상 급등 후 고점 대비 -10% 이상 반락)
        elif max_return_pct >= 20.0 and pct_from_peak <= -10.0:
            signal = "🎯 트레일링 익절 (Trailing Stop)"
            urgency = "WARNING"
            action_plan = f"최고 수익 +{max_return_pct:.1f}% 달성 후 고점 대비 {pct_from_peak:.1f}% 반락. 수익 보호 위해 전량 매도."

        # Rule 4: 본전 보호 스탑 (+12% 이상 올랐던 주식이 본전 근처로 반락)
        elif max_return_pct >= 12.0 and current_return_pct <= 1.0:
            signal = "🛡️ 본전 매도 (Break-Even)"
            urgency = "CRITICAL"
            action_plan = "큰 수익 후 원금 침범 방지 원칙. 원금 보호 위해 본전에서 즉시 전량 매도."

        # Rule 5: 클라이맥스 고점 분할 익절 (200일선 70%+ 과이격 & 3개월 80%+ 급등)
        elif ((current_price - ma200) / ma200 >= 0.70) and (pct_from_peak >= -3.0):
            signal = "⚡ 클라이맥스 고점 (Sell into Strength)"
            urgency = "WARNING"
            action_plan = "200일선 대비 과열 수직 급등. 미너비니 원칙: 강세 구간에서 보유 물량의 1/2 분할 익절."

        # Rule 6: 단기 20일선 이탈 조기 경고 (+15% 이상 수익 상태에서 20일선 하회)
        elif current_price < ma20 and max_return_pct >= 15.0:
            signal = "🟡 20일선 이탈 (단기 둔화)"
            urgency = "INFO"
            action_plan = "단기 모멘텀 둔화. 50일선 지지 여부를 주시하며 1/3 분할 매도 고려."

        return {
            "code": code,
            "name": name,
            "market": market,
            "buy_price": buy_price,
            "buy_date": buy_date,
            "shares": pos.get("shares", 1),
            "memo": pos.get("memo", ""),
            "current_price": current_price,
            "current_return_pct": round(current_return_pct, 2),
            "peak_price": peak_price,
            "peak_date": peak_date,
            "max_return_pct": round(max_return_pct, 2),
            "pct_from_peak": round(pct_from_peak, 2),
            "initial_stop_price": round(initial_stop_price, 2),
            "trailing_stop_price": round(trailing_stop_price, 2),
            "active_stop_price": round(active_stop_price, 2),
            "ma20": round(ma20, 2),
            "ma50": round(ma50, 2),
            "ma200": round(ma200, 2),
            "signal": signal,
            "urgency": urgency,
            "action_plan": action_plan,
        }
    except Exception as e:
        print(f"  ! {code} 분석 중 오류: {e}")
        return None


def run_sell_monitor() -> list[dict]:
    """포트폴리오의 모든 종목에 대해 미너비니 매도 신호를 점검합니다."""
    positions = load_portfolio()

    # 등록된 종목이 없으면 기본 샘플 자동 생성
    if not positions:
        print("▶ 등록된 보유 종목이 없어 최근 스크리닝 상위 대표 종목으로 기본 포트폴리오를 구성합니다...")
        positions = [
            {"code": "000500", "name": "가온전선", "market": "KR", "buy_price": 310000, "buy_date": "2026-09-15", "shares": 10, "memo": "미너비니 SEPA 돌파 매수"},
            {"code": "222800", "name": "심텍", "market": "KR", "buy_price": 140000, "buy_date": "2026-09-10", "shares": 20, "memo": "코스닥 글로벌 10일 연속"},
            {"code": "144960", "name": "뉴파워프라즈마", "market": "KR", "buy_price": 12000, "buy_date": "2026-09-21", "shares": 100, "memo": "4일 전 신규 편입 돌파"},
            {"code": "HZO", "name": "MarineMax Inc", "market": "US", "buy_price": 24.50, "buy_date": "2026-09-14", "shares": 50, "memo": "미국 SEPA 1위"},
            {"code": "AMD", "name": "Advanced Micro Devices", "market": "US", "buy_price": 145.0, "buy_date": "2026-09-15", "shares": 15, "memo": "반도체 주도주"},
        ]
        save_portfolio(positions)

    print("\n" + "=" * 80)
    print(f" 🛡️ [마크 미너비니 포트폴리오 매도 시점 실시간 정밀 감시 엔진] 🛡️")
    print(f" - 분석 대상: 총 {len(positions)}개 보유 종목 (KR & US)")
    print("=" * 80 + "\n")

    results = []
    for pos in positions:
        res = analyze_single_position(pos)
        if res:
            results.append(res)

    if not results:
        print("❌ 분석 가능한 보유 종목 데이터가 없습니다.")
        return []

    # 결과 캐시 파일 저장
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 콘솔 요약 테이블 출력
    print_sell_summary_table(results)

    # 위험 경보(CRITICAL, WARNING) 발생 시 텔레그램 경보 발송
    send_sell_alert_telegram(results)

    return results


def print_sell_summary_table(results: list[dict]) -> None:
    """콘솔에 매도 감시 결과 표를 깔끔하게 출력합니다."""
    rows = []
    for r in results:
        is_us = r["market"] == "US"
        buy_s = f"${r['buy_price']:,.2f}" if is_us else f"{int(r['buy_price']):,}원"
        curr_s = f"${r['current_price']:,.2f}" if is_us else f"{int(r['current_price']):,}원"
        stop_s = f"${r['active_stop_price']:,.2f}" if is_us else f"{int(r['active_stop_price']):,}원"

        rows.append([
            f"{r['name']} ({r['code']})",
            r["market"],
            buy_s,
            curr_s,
            f"{r['current_return_pct']:+.1f}%",
            f"+{r['max_return_pct']:.1f}%",
            f"{r['pct_from_peak']:.1f}%",
            r["signal"],
            stop_s,
        ])

    headers = ["종목명 (코드)", "시장", "매수가", "현재가", "현재수익", "최고수익", "고점거리", "미너비니 매도진단", "권장스탑선"]
    print(tabulate(rows, headers=headers, tablefmt="fancy_grid", stralign="center"))
    print("\n💡 세부 권장 대응 액션:")
    for r in results:
        print(f" • [{r['code']} {r['name']}]: {r['action_plan']}")
    print()


def send_sell_alert_telegram(results: list[dict]) -> None:
    """긴급 손절 또는 익절 등 매도 신호 발생 시 텔레그램으로 즉시 알림을 발송합니다."""
    urgent_items = [r for r in results if r["urgency"] in ["CRITICAL", "WARNING"]]
    if not urgent_items:
        return

    bot_token, chat_id = load_telegram_config()
    if not bot_token or not chat_id:
        return

    import requests
    today_str = datetime.now().strftime("%Y-%m-%d")

    msg_lines = [
        f"🚨 <b>[마크 미너비니 포트폴리오 매도 경보]</b> ({today_str})\n",
        f"보유 종목 중 <b>{len(urgent_items)}개 종목</b>이 미너비니 매도 신호에 도달했습니다!\n",
    ]

    for item in urgent_items:
        is_us = item["market"] == "US"
        p_str = f"${item['current_price']:,.2f}" if is_us else f"{int(item['current_price']):,}원"
        msg_lines.append(f"━━━━━━━━━━━━━━━━━━")
        msg_lines.append(f"📌 <b>{item['name']} ({item['code']})</b> [{item['market']}]")
        msg_lines.append(f"• 현재가: {p_str} (수익률: <b>{item['current_return_pct']:+.1f}%</b>)")
        msg_lines.append(f"• 고점 대비: {item['pct_from_peak']:.1f}% (최고수익: +{item['max_return_pct']:.1f}%)")
        msg_lines.append(f"• 진단: <b>{item['signal']}</b>")
        msg_lines.append(f"👉 <b>대응:</b> {item['action_plan']}\n")

    msg_lines.append(f"📊 웹 대시보드에서 전체 포트폴리오 상태를 확인하세요:")
    msg_lines.append(f"https://jungkbugk.github.io/minervini-krx/")

    text = "\n".join(msg_lines)
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(api_url, json=payload, timeout=10)
        if r.status_code == 200:
            print(f"📲 텔레그램 매도 경보 메시지 발송 완료! ({len(urgent_items)}건 감지)")
    except Exception as e:
        print(f"텔레그램 발송 실패: {e}")


if __name__ == "__main__":
    run_sell_monitor()
