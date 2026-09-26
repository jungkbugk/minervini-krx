"""마크 미너비니 스크리너 텔레그램 알림 모듈"""

from __future__ import annotations

import json
import os
import requests

CONFIG_FILE = "telegram_config.json"


def load_telegram_config() -> tuple[str, str]:
    """저장된 텔레그램 봇 토큰과 Chat ID를 불러옵니다."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                token = data.get("bot_token", token)
                chat_id = data.get("chat_id", chat_id)
        except Exception:
            pass

    return token, chat_id


def save_telegram_config(token: str, chat_id: str) -> None:
    """텔레그램 설정을 저장합니다."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"bot_token": token, "chat_id": chat_id}, f, indent=2)


def format_marcap(val: float | int) -> str:
    """시가총액을 간단한 단위로 변환합니다."""
    if not val or val <= 0:
        return "-"
    val = int(val)
    cho = val // 1_000_000_000_000
    eok = (val % 1_000_000_000_000) // 100_000_000
    if cho > 0:
        return f"{cho}조 {eok:,}억" if eok > 0 else f"{cho}조"
    return f"{eok:,}억"


def build_telegram_message(
    today_str: str,
    total_passed: int,
    top_stocks: list[dict],
    new_entrants: list[dict],
    dropped_stocks: list[dict],
    dashboard_url: str = "https://jungkbugk.github.io/minervini-krx/",
) -> str:
    """텔레그램에 전송할 마크다운 서식 메시지를 생성합니다."""
    lines = []
    lines.append("🚀 *[마크 미너비니 SEPA 데일리 리포트]*")
    lines.append(f"📅 *기준일자*: {today_str}")
    lines.append(f"📊 *조건 통과 주도주*: 총 *{total_passed}개* 종목\n")

    # 1. 신규 편입 종목 (NEW)
    lines.append(f"🔥 *[오늘 신규 편입된 종목]* ({len(new_entrants)}개)")
    if new_entrants:
        for s in new_entrants[:10]:  # 최대 10개까지 표시
            high_dist = f"{s['pct_from_52w_high']:+.1f}%"
            vcp_str = "🟢VCP수축" if s.get("vcp_ratio", 1.0) < 0.85 else "🟡양호"
            mcap = format_marcap(s.get("marcap", 0))
            lines.append(
                f"• *{s['name']}* (`{s['code']}`) : *{s['close']:,}원*\n"
                f"   └ SEPA *{s['sepa_score']}점* | 52주고점 *{high_dist}* | {vcp_str} | {mcap}"
            )
        if len(new_entrants) > 10:
            lines.append(f"   *(외 {len(new_entrants) - 10}개 종목 대시보드 참조)*")
    else:
        lines.append("• 오늘 새롭게 편입된 종목은 없습니다. (기존 추세 유지)")
    lines.append("")

    # 2. 조건 이탈 종목 (DROPPED)
    lines.append(f"🚨 *[전일 대비 조건 이탈/탈락 종목]* ({len(dropped_stocks)}개)")
    if dropped_stocks:
        for s in dropped_stocks[:8]:  # 최대 8개까지 표시
            days = s.get("consecutive_days", 1)
            lines.append(f"• *{s['name']}* (`{s['code']}`) : 연속 {days}일 유지 후 탈락 (추세 이탈 주의)")
        if len(dropped_stocks) > 8:
            lines.append(f"   *(외 {len(dropped_stocks) - 8}개 종목 탈락)*")
    else:
        lines.append("• 이탈 종목 없음 (기존 주도주 강세 유지)")
    lines.append("")

    # 3. SEPA 종합 TOP 5 주도주 (연속 일수 포함)
    lines.append("👑 *[SEPA 종합 추천 TOP 5 (연속 일수)]*")
    for idx, s in enumerate(top_stocks[:5], start=1):
        days_str = s.get("status_label", "")
        lines.append(
            f"{idx}. *{s['name']}* (`{s['code']}`) - *{s['sepa_score']}점*\n"
            f"    └ {s['close']:,}원 | {days_str} | 거래대금 {s['avg_trading_val_20d']:.1f}억"
        )
    lines.append("")

    # 4. 대시보드 링크
    lines.append(f"🌐 *실시간 인터랙티브 웹 대시보드*:\n{dashboard_url}")

    return "\n".join(lines)


def send_telegram_alert(
    today_str: str,
    total_passed: int,
    top_stocks: list[dict],
    new_entrants: list[dict],
    dropped_stocks: list[dict],
) -> bool:
    """텔레그램 메시지를 발송합니다."""
    token, chat_id = load_telegram_config()
    if not token or not chat_id:
        print("\n💡 텔레그램 설정이 아직 등록되지 않았습니다.")
        print("   (텔레그램 봇 토큰과 Chat ID를 등록하시면 매일 자동으로 텔레그램 알림톡이 전송됩니다)")
        return False

    message_text = build_telegram_message(
        today_str=today_str,
        total_passed=total_passed,
        top_stocks=top_stocks,
        new_entrants=new_entrants,
        dropped_stocks=dropped_stocks,
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("📲 텔레그램 알림 메시지 발송 완료!")
            return True
        else:
            print(f"❌ 텔레그램 발송 실패 (HTTP {r.status_code}): {r.text}")
            return False
    except Exception as e:
        print(f"❌ 텔레그램 발송 중 네트워크 오류: {e}")
        return False
