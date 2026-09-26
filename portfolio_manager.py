"""마크 미너비니 포트폴리오 관리자 (보유 종목 등록, 삭제, 조회)"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Windows 콘솔 UTF-8 설정
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PORTFOLIO_FILE = "portfolio.json"


def load_portfolio() -> list[dict]:
    """저장된 포트폴리오 종목 목록을 불러옵니다."""
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_portfolio(positions: list[dict]) -> None:
    """포트폴리오 종목 목록을 저장합니다."""
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def add_position(
    code: str,
    name: str = "",
    market: str = "KR",
    buy_price: float = 0.0,
    buy_date: str = "",
    shares: int = 1,
    memo: str = "",
) -> None:
    """포트폴리오에 새 종목을 추가하거나 기존 종목을 갱신합니다."""
    positions = load_portfolio()
    code = str(code).strip().upper()
    market = market.strip().upper()

    if not buy_date:
        from datetime import datetime
        buy_date = datetime.now().strftime("%Y-%m-%d")

    # 기존 종목 여부 확인
    existing_idx = None
    for idx, p in enumerate(positions):
        if str(p["code"]).upper() == code:
            existing_idx = idx
            break

    item = {
        "code": code,
        "name": name or code,
        "market": market,
        "buy_price": float(buy_price),
        "buy_date": buy_date,
        "shares": int(shares),
        "memo": memo,
    }

    if existing_idx is not None:
        positions[existing_idx] = item
        print(f"✓ 기존 종목 갱신 완료: [{market}] {item['name']} ({code}) - 매수가: {buy_price:,.2f}")
    else:
        positions.append(item)
        print(f"✓ 새 보유 종목 등록 완료: [{market}] {item['name']} ({code}) - 매수가: {buy_price:,.2f}")

    save_portfolio(positions)


def remove_position(code: str) -> None:
    """포트폴리오에서 종목을 제거합니다."""
    positions = load_portfolio()
    code = str(code).strip().upper()
    before_len = len(positions)
    positions = [p for p in positions if str(p["code"]).upper() != code]

    if len(positions) < before_len:
        save_portfolio(positions)
        print(f"✓ 종목 삭제 완료: {code}")
    else:
        print(f"! 해당 종목을 찾을 수 없습니다: {code}")


def list_positions() -> None:
    """현재 등록된 보유 종목 목록을 출력합니다."""
    positions = load_portfolio()
    if not positions:
        print("\n[!] 현재 등록된 보유 종목이 없습니다.")
        print("    사용법: python portfolio_manager.py --add <종목코드> --price <매수가> [--name <종목명>] [--market KR|US]")
        return

    print("\n" + "=" * 80)
    print(f" 💼 [내 보유 종목 포트폴리오 목록] (총 {len(positions)}개 종목)")
    print("=" * 80)
    print(f"{'순번':<4} {'시장':<6} {'코드/티커':<10} {'종목명':<20} {'매수가':<14} {'매수일자':<12} {'수량':<6} {'메모'}")
    print("-" * 80)
    for idx, p in enumerate(positions, 1):
        price_str = f"${p['buy_price']:,.2f}" if p['market'] == 'US' else f"{int(p['buy_price']):,}원"
        print(f"{idx:<4} {p['market']:<6} {p['code']:<10} {p.get('name', p['code'])[:18]:<20} {price_str:<14} {p.get('buy_date', ''):<12} {p.get('shares', 1):<6} {p.get('memo', '')}")
    print("=" * 80 + "\n")


def interactive_mode():
    """터미널에서 대화형으로 종목을 등록하는 모드"""
    print("\n" + "=" * 60)
    print(" 💼 [마크 미너비니 포트폴리오 대화형 등록기]")
    print("=" * 60)

    while True:
        print("\n1. 보유 종목 추가/수정")
        print("2. 보유 종목 삭제")
        print("3. 보유 종목 목록 보기")
        print("4. 종료")
        choice = input("\n메뉴 번호를 선택하세요 (1-4): ").strip()

        if choice == "1":
            code = input("종목코드 또는 미국 티커 (예: 000500, AAPL): ").strip().upper()
            if not code: continue
            name = input("종목명 (엔터 치면 자동/코드사용): ").strip()
            market_in = input("시장 (1: 한국(KR), 2: 미국(US), 기본: 1): ").strip()
            market = "US" if market_in == "2" else "KR"
            price = input("매수단가 (예: 318000 또는 150.5): ").strip()
            date = input("매수일자 (YYYY-MM-DD, 엔터 치면 오늘): ").strip()
            shares = input("보유수량 (기본 1): ").strip() or "1"
            memo = input("메모 (선택사항): ").strip()

            add_position(
                code=code,
                name=name,
                market=market,
                buy_price=float(price) if price else 0,
                buy_date=date,
                shares=int(shares) if shares.isdigit() else 1,
                memo=memo
            )
        elif choice == "2":
            code = input("삭제할 종목코드 또는 티커: ").strip().upper()
            if code: remove_position(code)
        elif choice == "3":
            list_positions()
        elif choice == "4":
            print("종료합니다.")
            break


def main():
    parser = argparse.ArgumentParser(description="마크 미너비니 포트폴리오 관리 도구")
    parser.add_argument("--add", type=str, help="추가할 종목코드 (예: 000500, HZO)")
    parser.add_argument("--name", type=str, default="", help="종목명")
    parser.add_argument("--market", type=str, default="KR", choices=["KR", "US"], help="시장 (KR, US)")
    parser.add_argument("--price", type=float, default=0.0, help="매수가격")
    parser.add_argument("--date", type=str, default="", help="매수일자 (YYYY-MM-DD)")
    parser.add_argument("--shares", type=int, default=1, help="보유 주식 수")
    parser.add_argument("--memo", type=str, default="", help="메모")
    parser.add_argument("--remove", type=str, help="삭제할 종목코드")
    parser.add_argument("--list", action="store_true", help="보유 종목 목록 출력")

    args = parser.parse_args()

    if args.add:
        add_position(
            code=args.add,
            name=args.name,
            market=args.market,
            buy_price=args.price,
            buy_date=args.date,
            shares=args.shares,
            memo=args.memo,
        )
    elif args.remove:
        remove_position(args.remove)
    elif args.list:
        list_positions()
    else:
        # 인자 없으면 목록 출력 후 대화형 실행
        list_positions()
        interactive_mode()


if __name__ == "__main__":
    main()
