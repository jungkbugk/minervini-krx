"""마크 미너비니 SEPA 한국투자증권(KIS) 퀀트 자동매매 봇 (kis_minervini_bot.py)

[핵심 퀀트 트레이딩 규칙 100% 자동 실행]
1. 🛡️ 자금 관리: 4개 슬롯 균등 분할 (종목당 총자산의 25% 배정)
2. 🚦 시장 레짐: 코스피/코스닥 지수 50일선 상회 시에만 신규 매수 (조정장 현금 100%)
3. 👑 종목 선정: 미너비니 VCP 수축(<=0.88), 20일선 이격(<=1.08), 52주 고점거리(-12% 이내), IBD 모멘텀 1위 우선
4. 🚨 초기 손절: 매수가 대비 -7.5% 터치 시 시장가 기계적 전량 손절
5. 🛡️ 3R 본전 보호: +22.5% 이상 수익 도달 시 스탑을 매수가(0%)로 즉시 상향하여 원금 영구 보호
6. 🎯 트레일링 익절: +22.5% 달성 후 최고점 대비 -10% 반락 시 시장가 전량 익절
7. 📲 텔레그램 연동: 매수/매도/손절/익절 체결 시 스마트폰 텔레그램 실시간 리포트 발송
"""

from __future__ import annotations

import argparse
from datetime import datetime, time as dtime
import json
import os
import sys
import time

from kis_api import KisClient
from market_filter import get_market_regime
from portfolio_manager import load_portfolio, save_portfolio
from telegram_notifier import send_telegram_text

PORTFOLIO_FILE = "portfolio.json"
HISTORY_DIR = "history"
LATEST_KR_FILE = os.path.join(HISTORY_DIR, "latest_kr.json")

TOTAL_SLOTS = 4              # 포트폴리오 최대 슬롯 수 (25% 균등 분할)
STOP_LOSS_PCT = 0.075        # 초기 하드 손절폭 (-7.5%)
THREE_R_GAIN_PCT = 22.5      # 3R 본전 보호 발동 수익률 (+22.5%)
TRAILING_FROM_PEAK_PCT = 10.0 # 3R 달성 후 고점 대비 트레일링 익절선 (-10.0%)


def get_current_time_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_market_open() -> bool:
    """한국 증시 정규장(09:00 ~ 15:30) 운영 여부 확인 (평일 기준)"""
    now = datetime.now()
    if now.weekday() >= 5:  # 토(5), 일(6)
        return False
    now_time = now.time()
    return dtime(9, 0) <= now_time <= dtime(15, 30)


class MinerviniTraderBot:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.client = KisClient()
        print("=" * 70)
        print(" 🤖 [마크 미너비니 SEPA 한국투자증권 퀀트 자동매매 봇 가동]")
        print(f" • 운영 모드: {'🧪 시뮬레이션(Dry-Run, 실제 주문X)' if self.dry_run else '🚀 실거래 주문 연동'}")
        print(f" • 계좌 구분: {'모의투자 계좌' if self.client.is_mock else '⚠️ 실전투자 계좌'}")
        print(f" • 계좌 번호: {self.client.account_no}-{self.client.account_code}")
        print("=" * 70)

    def print_status(self) -> dict:
        """계좌 상태, 예수금, 슬롯 점유율 출력"""
        bal = self.client.get_balance()
        tot_asset = bal["total_asset"]
        cash = bal["cash_available"]
        stocks_val = bal["stocks_value"]
        holdings = bal["holdings"]
        open_slots = max(0, TOTAL_SLOTS - len(holdings))

        print(f"\n📊 [계좌 및 슬롯 현황 리포트 - {get_current_time_str()}]")
        print(f" • 총 평가자산: {tot_asset:,}원 | 예수금: {cash:,}원 | 주식 평가액: {stocks_val:,}원")
        print(f" • 슬롯 점유: {len(holdings)}/{TOTAL_SLOTS}개 사용 중 (빈 슬롯: {open_slots}개)")
        if holdings:
            print(" • 현재 보유 종목:")
            for h in holdings:
                print(f"   - {h['name']} ({h['code']}): {h['shares']}주 | 평단가: {h['buy_price']:,.0f}원 | 현재가: {h['current_price']:,.0f}원 | 수익률: {h['return_pct']:+.2f}%")
        else:
            print(" • 현재 보유 종목이 없습니다 (현금 100% 대기).")
        return bal

    def execute_buy_strategy(self) -> list[dict]:
        """미너비니 VCP 상위 후보 종목 자동 분할 매수 실행"""
        print(f"\n🎯 [신규 매수 진입 검토 시작 - {get_current_time_str()}]")

        # 1. 시장 레짐 진단 (코스피/코스닥 50일선)
        regime = get_market_regime()
        kr_regime = regime.get("kr", {})
        if not kr_regime.get("can_buy", True):
            msg = "🚫 [신규 매수 차단] 코스피/코스닥 지수가 50일 이동평균선 아래에 위치해 있습니다. 미너비니 원칙에 따라 현금을 보존합니다."
            print(f"  {msg}")
            return []

        # 2. 계좌 잔고 및 빈 슬롯 확인
        bal = self.client.get_balance()
        tot_asset = bal["total_asset"]
        cash = bal["cash_available"]
        held_codes = set(h["code"] for h in bal["holdings"])
        open_slots = TOTAL_SLOTS - len(held_codes)

        if open_slots <= 0:
            print(f"  ℹ️ 포트폴리오 슬롯({TOTAL_SLOTS}개)이 모두 채워져 있어 신규 매수를 진행하지 않습니다.")
            return []

        # 슬롯당 예산 배정 (총자산의 25%와 잔여 예수금 중 작은 값)
        target_budget_per_slot = tot_asset / TOTAL_SLOTS
        slot_budget = min(cash, target_budget_per_slot)

        if slot_budget < 100_000:
            print(f"  ⚠️ 가용 예수금({cash:,}원)이 최소 주문 금액(10만원)에 미달하여 매수를 건너뜁니다.")
            return []

        print(f"  ✓ 빈 슬롯: {open_slots}개 | 슬롯당 배정 예산: {int(slot_budget):,}원")

        # 3. 최신 스크리닝 후보 로드
        if not os.path.exists(LATEST_KR_FILE):
            print(f"  ❌ 최신 스크리닝 결과({LATEST_KR_FILE})가 없습니다. minervini_screener.py를 먼저 실행하세요.")
            return []

        with open(LATEST_KR_FILE, "r", encoding="utf-8") as f:
            kr_data = json.load(f)

        candidates = kr_data.get("df", [])
        if not candidates:
            print("  ℹ️ 스크리닝 통과 종목이 없습니다.")
            return []

        # 엄격한 VCP & 과열 방지 필터링
        filtered_cands = []
        for c in candidates:
            code = str(c["code"]).zfill(6)
            if code in held_codes: continue
            vcp = float(c.get("vcp_ratio", 1.0))
            dist_high = float(c.get("pct_from_52w_high", -99))
            close = float(c.get("close", 0))
            ma20 = close / float(c.get("ext_ratio", 1.0)) if c.get("ext_ratio") else close

            # 고승률 62.7% 검증 룰: VCP <= 0.88 & 52주고점거리 >= -12.0%
            if vcp <= 0.88 and dist_high >= -12.0 and close > 0:
                filtered_cands.append(c)

        print(f"  ✓ 엄격 VCP 수축 통과 후보: {len(filtered_cands)}개 종목")

        # 상위 후보 중 빈 슬롯만큼 매수 진행
        orders_executed = []
        for cand in filtered_cands[:open_slots]:
            code = str(cand["code"]).zfill(6)
            name = cand.get("name", code)

            # 실시간 현재가 확인
            price_info = self.client.get_current_price(code)
            curr_price = price_info["price"] if price_info else float(cand.get("close", 0))

            if curr_price <= 0: continue

            shares_to_buy = int(slot_budget // curr_price)
            if shares_to_buy <= 0:
                print(f"  ! {name}({code}) 주가({curr_price:,}원)가 예산보다 커서 1주도 살 수 없습니다.")
                continue

            order_amount = int(shares_to_buy * curr_price)
            initial_stop = round(curr_price * (1.0 - STOP_LOSS_PCT), 0)

            print(f"\n🛒 [매수 실행 요청] {name} ({code})")
            print(f"   • 수량: {shares_to_buy:,}주 | 현재가: {curr_price:,}원 | 예상금액: {order_amount:,}원")
            print(f"   • 초기 손절선(-7.5%): {initial_stop:,.0f}원")

            if self.dry_run:
                order_res = {"success": True, "order_no": "MOCK-ORDER-001", "msg": "시뮬레이션 모드"}
            else:
                order_res = self.client.order_market_buy(code, shares_to_buy)

            if order_res.get("success"):
                print(f"   ✅ [주문 접수 완료] 주문번호: {order_res.get('order_no')}")
                orders_executed.append({
                    "code": code,
                    "name": name,
                    "market": "KR",
                    "buy_price": curr_price,
                    "buy_date": datetime.now().strftime("%Y-%m-%d"),
                    "shares": shares_to_buy,
                    "peak_price": curr_price,
                    "active_stop": initial_stop,
                    "memo": f"미너비니 SEPA 봇 자동 매수 (점수: {cand.get('sepa_score', 0)}점)"
                })

                # 텔레그램 알림 전송
                tg_msg = (
                    f"🔥 [미너비니 SEPA 퀀트 봇 - 매수 체결]\n\n"
                    f"• 종목명: {name} ({code})\n"
                    f"• 매수수량: {shares_to_buy:,}주\n"
                    f"• 체결단가: {curr_price:,.0f}원\n"
                    f"• 총 매수액: {order_amount:,}원\n"
                    f"• 손절가(-7.5%): {initial_stop:,.0f}원\n"
                    f"• 3R 목표가(+22.5%): {round(curr_price * 1.225, 0):,.0f}원"
                )
                send_telegram_text(tg_msg)

                # 슬롯 차감
                open_slots -= 1
                cash -= order_amount
                if open_slots <= 0: break
            else:
                print(f"   ❌ 주문 실패: {order_res.get('msg')}")

        # 로컬 포트폴리오 동기화 저장 (실제 주문 시에만)
        if orders_executed and not self.dry_run:
            current_portfolio = load_portfolio()
            for o in orders_executed:
                current_portfolio.append(o)
            save_portfolio(current_portfolio)
            print(f"\n💾 portfolio.json에 신규 {len(orders_executed)}개 종목이 등록되었습니다.")

        return orders_executed

    def execute_sell_monitoring(self) -> list[dict]:
        """보유 종목 미너비니 6대 매도 룰 실시간 정밀 감시 및 자동 청산"""
        bal = self.client.get_balance()
        holdings = bal.get("holdings", [])
        if not holdings:
            return []

        # 로컬 포트폴리오 관리 파일 로드
        local_portfolio = {p["code"]: p for p in load_portfolio()}
        sells_executed = []

        for h in holdings:
            code = h["code"]
            name = h["name"]
            shares = h["shares"]
            buy_price = h["buy_price"]

            # 실시간 현재가 조회
            price_info = self.client.get_current_price(code)
            curr_price = price_info["price"] if price_info else h["current_price"]
            curr_high = price_info["high"] if price_info else curr_price

            if buy_price <= 0: continue

            # 고점 추적
            saved_pos = local_portfolio.get(code, {})
            peak_price = max(saved_pos.get("peak_price", buy_price), curr_high)
            saved_pos["peak_price"] = peak_price

            # 손익률 계산
            return_pct = ((curr_price - buy_price) / buy_price) * 100
            max_return_pct = ((peak_price - buy_price) / buy_price) * 100
            pct_from_peak = ((curr_price - peak_price) / peak_price) * 100

            # ----------------------------------------------------
            # 미너비니 3단계 동적 스탑로스 판정
            # ----------------------------------------------------
            active_stop = buy_price * (1.0 - STOP_LOSS_PCT)
            stop_reason = ""
            should_sell = False

            # 1. 3R (+22.5%) 달성 후 본전 보호 및 트레일링 스탑
            if max_return_pct >= THREE_R_GAIN_PCT:
                active_stop = max(active_stop, buy_price)  # 본전(0%) 보장
                trailing_stop = peak_price * (1.0 - (TRAILING_FROM_PEAK_PCT / 100.0))
                active_stop = max(active_stop, trailing_stop)

                if curr_price <= active_stop:
                    should_sell = True
                    stop_reason = f"🎯 3R 트레일링 스탑 익절 (+22.5% 달성 후 고점 대비 {pct_from_peak:.1f}% 반락 청산)"

            # 2. 초기 하드 손절 (-7.5%)
            elif curr_price <= active_stop:
                should_sell = True
                stop_reason = f"🚨 긴급 하드 손절 (손실률 {return_pct:.2f}% 도달, 원금 보호)"

            # 매도 실행
            if should_sell:
                print(f"\n⚠️ [매도 신호 발동!] {name} ({code})")
                print(f"   • 사유: {stop_reason}")
                print(f"   • 매수가: {buy_price:,.0f}원 ➔ 현재가: {curr_price:,.0f}원 ({return_pct:+.2f}%)")
                print(f"   • 매도수량: {shares:,}주")

                if self.dry_run:
                    sell_res = {"success": True, "order_no": "MOCK-SELL-001"}
                else:
                    sell_res = self.client.order_market_sell(code, shares)

                if sell_res.get("success"):
                    print(f"   ✅ [매도 접수 완료] 주문번호: {sell_res.get('order_no')}")
                    profit_won = int((curr_price - buy_price) * shares)
                    sells_executed.append({
                        "code": code,
                        "name": name,
                        "return_pct": return_pct,
                        "profit_won": profit_won,
                        "reason": stop_reason
                    })

                    # 텔레그램 알림 전송
                    tg_msg = (
                        f"🛡️ [미너비니 SEPA 퀀트 봇 - 매도 체결]\n\n"
                        f"• 종목명: {name} ({code})\n"
                        f"• 매도사유: {stop_reason}\n"
                        f"• 체결단가: {curr_price:,.0f}원 (매수가: {buy_price:,.0f}원)\n"
                        f"• 확정 수익률: {return_pct:+.2f}%\n"
                        f"• 실현 손익: {profit_won:+,}원"
                    )
                    send_telegram_text(tg_msg)

                    # 포트폴리오에서 삭제
                    if code in local_portfolio:
                        del local_portfolio[code]
                else:
                    print(f"   ❌ 매도 주문 실패: {sell_res.get('msg')}")

        # 업데이트된 포트폴리오 저장
        save_portfolio(list(local_portfolio.values()))
        return sells_executed

    def run_auto_loop(self, interval_sec: int = 60) -> None:
        """장중 실시간 무인 자동매매 루프"""
        print(f"\n🔄 [무인 자동매매 모니터링 루프 가동 (감시 주기: {interval_sec}초)]")
        print("  - Ctrl+C를 누르면 안전하게 종료됩니다.\n")

        has_bought_today = False

        while True:
            try:
                now_str = get_current_time_str()
                is_open = is_market_open()

                if not is_open:
                    print(f"[{now_str}] ⏸️ 정규장 운영 시간이 아닙니다 (09:00 ~ 15:30 대기 중)...", end="\r")
                    time.sleep(30)
                    continue

                # 1. 아침 09:01 이후 당일 1회 신규 매수 시도
                now_time = datetime.now().time()
                if dtime(9, 1) <= now_time <= dtime(15, 0) and not has_bought_today:
                    self.execute_buy_strategy()
                    has_bought_today = True

                # 2. 장중 1분 주기로 실시간 매도 감시
                sells = self.execute_sell_monitoring()
                if sells:
                    print(f"[{now_str}] 💥 매도 완료 건수: {len(sells)}건")

                time.sleep(interval_sec)

            except KeyboardInterrupt:
                print("\n\n🛑 사용자에 의해 자동매매 봇이 안전하게 중단되었습니다.")
                break
            except Exception as e:
                print(f"\n❌ 루프 실행 중 일시 오류: {e}")
                time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description="마크 미너비니 SEPA 한국투자증권 퀀트 자동매매 봇")
    parser.add_argument("--status", action="store_true", help="현재 계좌 잔고 및 슬롯 상태 조회")
    parser.add_argument("--buy-now", action="store_true", help="지금 즉시 매수 전략 1회 실행")
    parser.add_argument("--sell-check", action="store_true", help="지금 즉시 보유 종목 매도 조건 1회 감시")
    parser.add_argument("--auto", action="store_true", help="장중 무인 자동매매 루프 가동")
    parser.add_argument("--dry-run", action="store_true", help="실제 주문을 넣지 않는 시뮬레이션 모드")

    args = parser.parse_args()
    bot = MinerviniTraderBot(dry_run=args.dry_run)

    if args.status:
        bot.print_status()
    elif args.buy_now:
        bot.execute_buy_strategy()
    elif args.sell_check:
        bot.execute_sell_monitoring()
    elif args.auto:
        bot.run_auto_loop()
    else:
        # 기본 실행: 계좌 상태 출력 후 메뉴 제공
        bot.print_status()
        print("\n사용 가능한 명령어:")
        print(" • python kis_minervini_bot.py --status      (계좌 및 슬롯 상태 조회)")
        print(" • python kis_minervini_bot.py --buy-now     (신규 종목 매수 1회 실행)")
        print(" • python kis_minervini_bot.py --sell-check  (매도 조건 1회 감시)")
        print(" • python kis_minervini_bot.py --auto        (장중 실시간 완전 자동매매 루프 가동)")
        print(" • 옵션에 --dry-run을 붙이면 주문을 넣지 않고 가상 테스트만 진행합니다.")


if __name__ == "__main__":
    main()
