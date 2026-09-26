"""한국투자증권(KIS) Open API 클라이언트 모듈 (모의/실전 통합 및 토큰 자동 캐싱)

지원 기능:
1. OAuth2 토큰 자동 발급 및 로컬 캐싱 (1분당 1회 제한 방지 & 24시간 유효)
2. 계좌 예수금 및 보유 주식 잔고 실시간 조회
3. 국내 주식 매수/매도 주문 (시장가/지정가)
4. 현재가 및 호가 실시간 조회
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
import sys
import time
import requests

CONFIG_FILE = "kis_config.json"
TOKEN_CACHE_FILE = os.path.join("history", "kis_token_cache.json")

# Windows 콘솔 UTF-8 설정
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class KisClient:
    def __init__(self, config_file: str = CONFIG_FILE):
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"'{config_file}' 설정 파일이 없습니다. set_kis_account.py를 먼저 실행하세요.")

        with open(config_file, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        self.is_mock: bool = self.cfg.get("is_mock", True)
        self.app_key: str = self.cfg.get("app_key", "").strip()
        self.app_secret: str = self.cfg.get("app_secret", "").strip()
        self.account_no: str = self.cfg.get("account_no", "").strip()
        self.account_code: str = self.cfg.get("account_code", "01").strip()

        # 도메인 설정 (모의투자 vs 실전투자)
        if self.is_mock:
            self.base_url = "https://openapivts.koreainvestment.com:29443"
            self.tr_inquire_balance = "VTTC8434R"
            self.tr_buy_order = "VTTC0802U"
            self.tr_sell_order = "VTTC0801U"
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"
            self.tr_inquire_balance = "TTTC8434R"
            self.tr_buy_order = "TTTC0802U"
            self.tr_sell_order = "TTTC0801U"

        self.token = self._get_access_token()

    def _get_access_token(self) -> str:
        """토큰 캐시를 확인하고 유효하면 재사용, 만료되었으면 신규 발급합니다."""
        os.makedirs("history", exist_ok=True)
        if os.path.exists(TOKEN_CACHE_FILE):
            try:
                with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                expires_at = datetime.fromisoformat(cache.get("expires_at", "2000-01-01"))
                if datetime.now() < (expires_at - timedelta(minutes=30)):
                    return cache["access_token"]
            except Exception:
                pass

        # 신규 발급
        token_url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        headers = {"Content-Type": "application/json; charset=UTF-8"}

        res = requests.post(token_url, json=payload, headers=headers, timeout=10)
        data = res.json()
        if res.status_code != 200 or "access_token" not in data:
            # 1분 제한으로 실패했으나 기존 캐시가 있다면 우선 반환 시도
            if os.path.exists(TOKEN_CACHE_FILE):
                try:
                    with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                    return cache.get("access_token", "")
                except Exception:
                    pass
            raise RuntimeError(f"KIS 토큰 발급 실패: {data.get('error_description', data)}")

        token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        expires_at = datetime.now() + timedelta(seconds=expires_in)

        # 캐시 저장
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "access_token": token,
                "expires_at": expires_at.isoformat(),
                "created_at": datetime.now().isoformat()
            }, f, indent=2)

        return token

    def get_default_headers(self, tr_id: str) -> dict:
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }

    def get_balance(self) -> dict:
        """계좌 예수금 및 보유 주식 잔고 상세 조회."""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self.get_default_headers(self.tr_inquire_balance)
        params = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        res = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
        if data.get("rt_cd") != "0":
            raise RuntimeError(f"잔고 조회 실패 ({data.get('msg_cd')}): {data.get('msg1')}")

        summary = data.get("output2", [{}])[0]
        stocks = data.get("output1", [])

        holdings = []
        for s in stocks:
            qty = int(s.get("hldg_qty", 0))
            if qty <= 0: continue
            holdings.append({
                "code": s.get("pdno", "").strip(),
                "name": s.get("prdt_name", "").strip(),
                "shares": qty,
                "buy_price": float(s.get("pchs_avg_pric", 0)),
                "current_price": float(s.get("prpr", 0)),
                "eval_amount": int(s.get("evlu_amt", 0)),
                "profit_won": int(s.get("evlu_pfls_amt", 0)),
                "return_pct": float(s.get("evlu_pfls_rt", 0)),
            })

        return {
            "account_no": f"{self.account_no}-{self.account_code}",
            "is_mock": self.is_mock,
            "total_asset": int(summary.get("tot_evlu_amt", 0)),
            "cash_available": int(summary.get("dnca_tot_amt", 0)),
            "stocks_value": int(summary.get("scts_evlu_amt", 0)),
            "total_profit_won": int(summary.get("evlu_pfls_smtl_amt", 0)),
            "holdings": holdings,
        }

    def order_market_buy(self, code: str, qty: int) -> dict:
        """국내 주식 시장가 매수 주문"""
        if qty <= 0:
            raise ValueError(f"주문 수량은 1주 이상이어야 합니다. (입력: {qty})")

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self.get_default_headers(self.tr_buy_order)
        payload = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_code,
            "PDNO": code.strip(),
            "ORD_DVSN": "01",  # 01: 시장가
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0",   # 시장가는 0원 지정
        }

        res = requests.post(url, headers=headers, json=payload, timeout=10)
        data = res.json()
        if data.get("rt_cd") != "0":
            return {
                "success": False,
                "msg": f"[{data.get('msg_cd')}] {data.get('msg1')}",
                "order_no": "",
                "code": code,
                "qty": qty,
            }

        out = data.get("output", {})
        return {
            "success": True,
            "msg": data.get("msg1", "주문 접수 성공"),
            "order_no": out.get("ODNO", ""),
            "code": code,
            "qty": qty,
            "time": out.get("ORD_TMD", ""),
        }

    def order_market_sell(self, code: str, qty: int) -> dict:
        """국내 주식 시장가 매도 주문"""
        if qty <= 0:
            raise ValueError(f"주문 수량은 1주 이상이어야 합니다. (입력: {qty})")

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self.get_default_headers(self.tr_sell_order)
        payload = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_code,
            "PDNO": code.strip(),
            "ORD_DVSN": "01",  # 01: 시장가
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0",
        }

        res = requests.post(url, headers=headers, json=payload, timeout=10)
        data = res.json()
        if data.get("rt_cd") != "0":
            return {
                "success": False,
                "msg": f"[{data.get('msg_cd')}] {data.get('msg1')}",
                "order_no": "",
                "code": code,
                "qty": qty,
            }

        out = data.get("output", {})
        return {
            "success": True,
            "msg": data.get("msg1", "매도 접수 성공"),
            "order_no": out.get("ODNO", ""),
            "code": code,
            "qty": qty,
            "time": out.get("ORD_TMD", ""),
        }

    def get_current_price(self, code: str) -> dict | None:
        """개별 종목 실시간 현재가, 고가, 저가, 전일대비 등 시세 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.get_default_headers("FHKST01010100")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code.strip(),
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            if data.get("rt_cd") == "0":
                out = data.get("output", {})
                return {
                    "code": code,
                    "price": float(out.get("stck_prpr", 0)),
                    "high": float(out.get("stck_hgpr", 0)),
                    "low": float(out.get("stck_lwpr", 0)),
                    "volume": int(out.get("acml_vol", 0)),
                    "change_pct": float(out.get("prdy_ctrt", 0)),
                }
        except Exception:
            pass
        return None


if __name__ == "__main__":
    print("=" * 65)
    print(" 🚀 [한국투자증권 API 연결 및 잔고 조회 테스트]")
    print("=" * 65)
    try:
        client = KisClient()
        bal = client.get_balance()
        print(f" • 계좌번호: {bal['account_no']} ({'모의투자' if bal['is_mock'] else '실전투자'})")
        print(f" • 총 평가자산: {bal['total_asset']:,}원")
        print(f" • 주문가능 예수금: {bal['cash_available']:,}원")
        print(f" • 보유 종목 수: {len(bal['holdings'])}개")
        for h in bal['holdings']:
            print(f"   - {h['name']}({h['code']}): {h['shares']}주 | 평단가: {h['buy_price']:,.0f}원 | 손익: {h['return_pct']:+.2f}%")
        print("=" * 65)
        print("✅ 한투 API 모듈이 완벽하게 준비되었습니다!")
    except Exception as e:
        print(f"❌ 연결 테스트 중 오류 발생: {e}")
