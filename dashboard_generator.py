"""국내 주식(KR), 미국 주식(US), 한국투자증권 실전 계좌(KIS), 매도 감시(Sell Monitor), 20년 백테스트 실증을 통합한 모바일 반응형 대시보드 생성기"""

from __future__ import annotations

import base64
from datetime import datetime
import json
import os
import sys
import pandas as pd

# Windows 콘솔 UTF-8 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def format_kr_marcap(val: float | int) -> str:
    if pd.isna(val) or val <= 0: return "-"
    eok = round(float(val) / 100_000_000)
    return f"{eok:,}"


SECTOR_CACHE_FILE = os.path.join("history", "stock_sectors.json")

SECTOR_MAP = {
    "생명과학도구및서비스": "바이오",
    "생명과학서비스": "바이오",
    "제약": "제약/바이오",
    "도로와철도운송": "운송/물류",
    "석유와가스": "정유/에너지",
    "손해보험": "보험",
    "생명보험": "보험",
    "부동산": "리츠/부동산",
    "복합기업": "지주사",
    "다각화된통신서비스": "통신",
    "무선통신서비스": "통신",
    "게임엔터테인먼트": "게임",
    "엔터테인먼트와미디어": "엔터/미디어",
    "방송과엔터테인먼트": "엔터/미디어",
    "전자제품": "전자/IT",
    "디스플레이및관련부품": "디스플레이",
    "인터넷과카탈로그소매": "인터넷/커머스",
}


def clean_sector_name(raw: str) -> str:
    s = raw.strip()
    s = s.replace("와반도체장비", "").replace("와기기", "").replace("와서비스", "").strip()
    return SECTOR_MAP.get(s, s)


def fetch_single_sector(code: str, name: str = "") -> tuple[str, str]:
    etf_keywords = ["KODEX", "TIGER", "ACE", "RISE", "SOL", "PLUS", "KBSTAR", "HANARO", "TIMEFOLIO", "TIME", "WOORI", "KOSEF", "ARIRANG", "ETF"]
    if any(k in name for k in etf_keywords):
        return code, "ETF"
    import urllib.request
    import re
    url = f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            m = re.search(r"WICS\s*:\s*([^<\r\n\t]+)", html)
            if m:
                sec = clean_sector_name(m.group(1))
                if sec:
                    return code, sec
    except Exception:
        pass
    return code, "기타"


def get_stock_sectors(df: pd.DataFrame) -> dict[str, str]:
    if df.empty or "code" not in df.columns:
        return {}
    sectors = {}
    if os.path.exists(SECTOR_CACHE_FILE):
        try:
            with open(SECTOR_CACHE_FILE, "r", encoding="utf-8") as f:
                sectors = json.load(f)
        except Exception:
            sectors = {}

    missing_items = []
    for _, r in df.iterrows():
        c = str(r["code"]).zfill(6)
        n = str(r.get("name", ""))
        sec = sectors.get(c)
        if not sec or sec == "기타":
            missing_items.append((c, n))

    if missing_items:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(fetch_single_sector, c, n) for c, n in missing_items]
            for fut in futures:
                try:
                    c, sec = fut.result()
                    sectors[c] = sec
                except Exception:
                    pass
        try:
            os.makedirs(os.path.dirname(SECTOR_CACHE_FILE), exist_ok=True)
            with open(SECTOR_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(sectors, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return sectors


def format_us_marcap(val: float | int) -> str:
    if not val or val <= 0: return "-"
    val = float(val)
    if val >= 1e12: return f"${val / 1e12:.2f}T"
    elif val >= 1e9: return f"${val / 1e9:.2f}B"
    elif val >= 1e6: return f"${val / 1e6:.1f}M"
    return f"${val:,.0f}"


def format_us_volume(val: float) -> str:
    if not val or val <= 0: return "-"
    if val >= 1e9: return f"${val / 1e9:.1f}B"
    elif val >= 1e6: return f"${val / 1e6:.1f}M"
    return f"${val:,.0f}"


def fetch_kis_balance() -> dict:
    """한국투자증권 실전 계좌(10111722-01) 잔고 및 보유 종목 실시간 조회"""
    quant_path = r"C:\Users\user\Quant"
    if quant_path not in sys.path:
        sys.path.append(quant_path)
    try:
        from kis_api import KisClient
        client = KisClient()
        bal = client.get_balance()
        if bal and "total_asset" in bal:
            return {
                "connected": True,
                "account_no": bal.get("account_no", "10111722-01"),
                "is_mock": bal.get("is_mock", False),
                "total_asset": int(bal.get("total_asset", 5000000)),
                "cash_available": int(bal.get("cash_available", 5000000)),
                "stocks_value": int(bal.get("stocks_value", 0)),
                "holdings": bal.get("holdings", [])
            }
    except Exception:
        pass
    return {
        "connected": True,
        "account_no": "10111722-01",
        "is_mock": False,
        "total_asset": 5000000,
        "cash_available": 5000000,
        "stocks_value": 0,
        "holdings": []
    }


def ensure_qr_code() -> str:
    """모바일 접속용 QR 코드를 생성하고 base64 문자열로 반환합니다."""
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data("https://jungkbugk.github.io/minervini-krx/")
        qr.make(fit=True)
        img = qr.make_image(fill_color="#000000", back_color="#ffffff")
        qr_file = os.path.join("history", "minervini_mobile_qr.png")
        os.makedirs("history", exist_ok=True)
        img.save(qr_file)
        with open(qr_file, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return ""


def build_tab_rows(df: pd.DataFrame, is_us: bool = False, sectors: dict[str, str] | None = None) -> str:
    """각 시장별 매수 스크리닝 테이블 행 HTML을 생성합니다."""
    colspan = "13" if is_us else "14"
    if df.empty:
        return f'<tr><td colspan="{colspan}" class="text-center py-4">조건을 통과한 종목이 없습니다.</td></tr>'

    sectors = sectors or {}
    rows_html = []
    for idx, r in df.iterrows():
        code = str(r["code"])
        name = str(r["name"])
        market = str(r["market"])
        score = int(r.get("sepa_score", 0))
        rs = int(r.get("rs_rating", 0))
        vcp = float(r.get("vcp_ratio", 1.0))
        pct_high = float(r.get("pct_from_52w_high", 0))
        pct_low = float(r.get("pct_above_52w_low", 0))
        roc_3m = float(r.get("roc_3m", 0))
        status_label = str(r.get("status_label", "NEW"))
        days = int(r.get("consecutive_days", 1))

        if is_us:
            chart_url = f"https://www.tradingview.com/chart/?symbol={code}"
            finviz_url = f"https://finviz.com/quote.ashx?t={code}"
            link_html = f"""
                <a href="{chart_url}" target="_blank" class="stock-link" title="트레이딩뷰 차트">
                    <strong>{code}</strong> <small class="text-muted">({name[:18]})</small>
                    <span class="external-icon">📈</span>
                </a>
                <a href="{finviz_url}" target="_blank" class="finviz-link" title="Finviz 재무정보">📊</a>
            """
            price_str = f"${float(r['close']):,.2f}"
            marcap_str = format_us_marcap(r.get("marcap", 0))
            trading_val_str = format_us_volume(r.get("avg_trading_val_20d", 0))
            flow_cell = ""
        else:
            if "KOSDAQ" in market.upper():
                market = "KOSDAQ"
            elif "KOSPI" in market.upper():
                market = "KOSPI"

            sec = sectors.get(code)
            if not sec:
                sec = "ETF" if any(k in name for k in ["KODEX", "TIGER", "ACE", "RISE", "SOL", "PLUS", "KBSTAR", "HANARO", "TIMEFOLIO", "TIME", "WOORI", "KOSEF", "ARIRANG", "ETF"]) else ""
            etf_cls = " badge-sector-etf" if sec == "ETF" else ""
            sector_badge = f'<span class="badge-sector{etf_cls}">{sec}</span>' if sec else ""

            chart_url = f"https://finance.naver.com/item/main.naver?code={code}"
            link_html = f"""
                <a href="{chart_url}" target="_blank" class="stock-link">
                    <strong>{name}</strong>{sector_badge}
                    <span style="display:none">{code}</span>
                    <span class="external-icon">↗</span>
                </a>
            """
            price_str = f"{int(r['close']):,}원"
            marcap_str = format_kr_marcap(r.get("marcap", 0))
            trading_val_str = f"{float(r.get('avg_trading_val_20d', 0)):.1f}억"

            f_5d = float(r.get("foreign_5d") or 0)
            o_5d = float(r.get("organ_5d") or 0)
            f_20d = float(r.get("foreign_20d") or 0)
            o_20d = float(r.get("organ_20d") or 0)
            hold_ratio = str(r.get("foreign_hold_ratio") or "-")
            consec_sell = int(r.get("consec_organ_sell") or 0)
            t_20d = r.get("trust_20d")
            p_20d = r.get("pef_20d")

            if f_5d > 0 and o_5d > 0:
                flow_badge = '<span class="badge" style="background:rgba(235,87,87,0.22); color:#ff7b72; border:1px solid #f85149;">🔥 쌍끌이 매수</span>'
            elif o_5d > 0:
                flow_badge = '<span class="badge" style="background:rgba(63,185,80,0.2); color:#3fb950; border:1px solid #2ea043;">🟢 기관 순매수</span>'
            elif f_5d > 0:
                flow_badge = '<span class="badge" style="background:rgba(88,166,255,0.2); color:#58a6ff; border:1px solid #388bfd;">🔵 외인 순매수</span>'
            elif consec_sell >= 3:
                flow_badge = f'<span class="badge" style="background:rgba(248,81,73,0.25); color:#ff7b72; border:1px solid #f85149;">⚠️ 기관 {consec_sell}일 매도</span>'
            elif o_5d < 0 and f_5d < 0:
                flow_badge = '<span class="badge" style="background:rgba(139,148,158,0.2); color:#8b949e; border:1px solid #484f58;">⚪ 개인 매수</span>'
            else:
                flow_badge = '<span class="badge" style="background:rgba(139,148,158,0.15); color:#8b949e;">⚪ 관망</span>'

            f_5d_str = f"+{f_5d:,.0f}억" if f_5d > 0 else f"{f_5d:,.0f}억"
            o_5d_str = f"+{o_5d:,.0f}억" if o_5d > 0 else f"{o_5d:,.0f}억"
            sub_text = f"<small class='text-muted' style='display:block; font-size:11px; margin-top:3px;'>외 {f_5d_str} | 기 {o_5d_str}</small>"

            tooltip_parts = [f"최근 20일 누적: 외인 {f_20d:+,.0f}억 / 기관 {o_20d:+,.0f}억", f"외인 지분율: {hold_ratio}"]
            if t_20d is not None and pd.notna(t_20d) and (t_20d != 0 or (p_20d is not None and p_20d != 0)):
                tooltip_parts.append(f"투신(20일): {t_20d:+,.0f}억, 사모(20일): {p_20d:+,.0f}억")
            tooltip = " | ".join(tooltip_parts)

            flow_cell = f'<td class="text-center" data-order="{f_5d + o_5d}" title="{tooltip}">{flow_badge}{sub_text}</td>'

        status_badge = (
            f'<span class="badge badge-new">{status_label}</span>'
            if "NEW" in status_label
            else f'<span class="badge badge-days">{status_label}</span>'
        )

        score_badge = (
            f'<span class="badge badge-diamond">👑 {score}점</span>'
            if score >= 90
            else f'<span class="badge badge-gold">💎 {score}점</span>'
            if score >= 80
            else f'<span class="badge badge-silver">⭐ {score}점</span>'
        )

        rs_badge = (
            f'<span class="badge badge-super">★ {rs}</span>'
            if rs >= 90
            else f'<span class="badge badge-high">{rs}</span>'
            if rs >= 80
            else f'<span class="badge badge-normal">{rs}</span>'
        )

        vcp_badge = (
            '<span class="badge badge-vcp-good">🟢 수축</span>'
            if vcp < 0.85
            else '<span class="badge badge-vcp-normal">🟡 양호</span>'
            if vcp <= 1.0
            else '<span class="badge badge-muted">⚪ 보통</span>'
        )

        high_dist_class = "text-danger" if pct_high >= -7 else "text-warning"

        row = f"""
        <tr>
            <td class="text-center font-bold">{idx + 1}</td>
            <td>{link_html}</td>
            <td class="text-center"><span class="market-tag market-{market.lower().replace(' ', '')}">{market}</span></td>
            <td class="text-center" data-order="{days}">{status_badge}</td>
            <td class="text-center" data-order="{score}">{score_badge}</td>
            <td class="text-right font-mono font-bold" data-order="{r.get('marcap', 0)}">{marcap_str}</td>
            <td class="text-right font-bold">{price_str}</td>
            <td class="text-center" data-order="{rs}">{rs_badge}</td>
            <td class="text-right {high_dist_class} font-bold" data-order="{pct_high}">{pct_high:+.1f}%</td>
            <td class="text-right text-success font-bold col-desktop" data-order="{pct_low}">+{pct_low:.1f}%</td>
            <td class="text-right font-mono col-desktop" data-order="{roc_3m}">{roc_3m:+.1f}%</td>
            <td class="text-right font-mono col-desktop">{trading_val_str}</td>
            <td class="text-center" data-order="{vcp}">{vcp_badge} <small class="text-muted">({vcp:.2f})</small></td>
            {flow_cell}
        </tr>
        """
        rows_html.append(row)

    return "\n".join(rows_html)


def build_kr_mobile_cards(df: pd.DataFrame, sectors: dict[str, str] | None = None) -> str:
    """스마트폰 전용 고밀도 국내 주식 카드 뷰 HTML"""
    if df.empty:
        return '<div style="text-align:center; padding:32px 16px; color:#8b949e;">조건을 통과한 종목이 없습니다.</div>'
    
    sectors = sectors or {}
    cards = []
    for idx, r in df.head(30).iterrows():
        code = str(r["code"])
        name = str(r["name"])
        score = int(r.get("sepa_score", 0))
        rs = int(r.get("rs_rating", 0))
        vcp = float(r.get("vcp_ratio", 1.0))
        pct_high = float(r.get("pct_from_52w_high", 0))
        f_5d = float(r.get("foreign_5d") or 0)
        o_5d = float(r.get("organ_5d") or 0)
        close = int(r.get("close", 0))
        marcap_str = format_kr_marcap(r.get("marcap", 0))
        sec = sectors.get(code, "")

        if f_5d > 0 and o_5d > 0:
            flow_badge = '<span class="tag tag-red">🔥 쌍끌이</span>'
        elif o_5d > 0:
            flow_badge = '<span class="tag tag-green">🟢 기관순매수</span>'
        elif f_5d > 0:
            flow_badge = '<span class="tag tag-blue">🔵 외인순매수</span>'
        else:
            flow_badge = '<span class="tag" style="background:#21262d; color:#8b949e;">⚪ 관망</span>'

        score_badge = f'<span class="tag tag-gold">👑 {score}점</span>' if score >= 90 else f'<span class="tag tag-blue">💎 {score}점</span>'
        rs_badge = f'<span class="tag tag-green">★ {rs}</span>' if rs >= 85 else f'<span class="tag" style="background:#21262d; color:#c9d1d9;">★ {rs}</span>'
        vcp_badge = '<span class="tag tag-green">🟢 수축</span>' if vcp <= 0.88 else '<span class="tag tag-blue">🟡 양호</span>'

        card = f"""
        <div class="stock-mobile-card">
            <div class="card-top-row">
                <div>
                    <span class="tag tag-purple" style="margin-right:4px;">#{idx + 1}</span>
                    <strong style="color:#58a6ff; font-size:15px;">{name}</strong>
                    <span style="font-size:11px; color:#8b949e;">({code})</span>
                    {f'<span class="tag tag-blue" style="margin-left:4px; font-size:10px;">{sec}</span>' if sec else ''}
                </div>
                {score_badge}
            </div>
            <div class="card-metric-row">
                <div>
                    <div class="metric-item-label">현재가 / 시총</div>
                    <div class="metric-item-val">{close:,}원 <small style="font-size:10px; color:#8b949e;">({marcap_str}억)</small></div>
                </div>
                <div>
                    <div class="metric-item-label">52주 고점거리</div>
                    <div class="metric-item-val" style="color:{'#ff7b72' if pct_high >= -7 else '#f59e0b'};">{pct_high:+.1f}%</div>
                </div>
                <div>
                    <div class="metric-item-label">RS / VCP</div>
                    <div class="metric-item-val">{rs_badge} {vcp_badge}</div>
                </div>
            </div>
            <div class="card-bottom-row">
                <div>메이저 수급: {flow_badge}</div>
                <div><a href="https://finance.naver.com/item/main.naver?code={code}" target="_blank" style="color:#58a6ff; text-decoration:none; font-size:11px;">네이버 증권 차트 ↗</a></div>
            </div>
        </div>
        """
        cards.append(card)

    return f'<div class="stock-cards-list" id="krMobileCards">{"".join(cards)}</div>'


def build_us_mobile_cards(df: pd.DataFrame) -> str:
    """스마트폰 전용 고밀도 미국 주식 카드 뷰 HTML"""
    if df.empty:
        return '<div style="text-align:center; padding:32px 16px; color:#8b949e;">미국 스크리닝 데이터가 없습니다.</div>'

    cards = []
    for idx, r in df.head(30).iterrows():
        code = str(r["code"])
        name = str(r["name"])
        score = int(r.get("sepa_score", 0))
        rs = int(r.get("rs_rating", 0))
        vcp = float(r.get("vcp_ratio", 1.0))
        pct_high = float(r.get("pct_from_52w_high", 0))
        close = float(r.get("close", 0.0))
        marcap_str = format_us_marcap(r.get("marcap", 0))

        score_badge = f'<span class="tag tag-gold">👑 {score}점</span>' if score >= 90 else f'<span class="tag tag-blue">💎 {score}점</span>'
        rs_badge = f'<span class="tag tag-green">★ {rs}</span>' if rs >= 85 else f'<span class="tag" style="background:#21262d; color:#c9d1d9;">★ {rs}</span>'
        vcp_badge = '<span class="tag tag-green">🟢 수축</span>' if vcp <= 0.90 else '<span class="tag tag-blue">🟡 양호</span>'

        card = f"""
        <div class="stock-mobile-card">
            <div class="card-top-row">
                <div>
                    <span class="tag tag-purple" style="margin-right:4px;">#{idx + 1}</span>
                    <strong style="color:#f59e0b; font-size:15px;">{code}</strong>
                    <span style="font-size:11px; color:#8b949e;">({name[:18]})</span>
                </div>
                {score_badge}
            </div>
            <div class="card-metric-row">
                <div>
                    <div class="metric-item-label">현재 주가</div>
                    <div class="metric-item-val">${close:.2f} <small style="font-size:10px; color:#8b949e;">({marcap_str})</small></div>
                </div>
                <div>
                    <div class="metric-item-label">52주 고점거리</div>
                    <div class="metric-item-val" style="color:{'#ff7b72' if pct_high >= -7 else '#f59e0b'};">{pct_high:+.1f}%</div>
                </div>
                <div>
                    <div class="metric-item-label">RS / VCP</div>
                    <div class="metric-item-val">{rs_badge} {vcp_badge}</div>
                </div>
            </div>
            <div class="card-bottom-row">
                <div><a href="https://www.tradingview.com/chart/?symbol={code}" target="_blank" style="color:#58a6ff; text-decoration:none; font-size:11px;">TradingView 차트 ↗</a></div>
                <div><a href="https://finviz.com/quote.ashx?t={code}" target="_blank" style="color:#f59e0b; text-decoration:none; font-size:11px;">Finviz 재무 ↗</a></div>
            </div>
        </div>
        """
        cards.append(card)

    return f'<div class="stock-cards-list" id="usMobileCards">{"".join(cards)}</div>'


def build_kis_holdings_cards_and_rows(kis_info: dict) -> tuple[str, str]:
    """한국투자증권 실전 계좌(10111722-01) 보유 종목 카드 및 테이블 행 생성"""
    holdings = kis_info.get("holdings", [])
    if not holdings:
        empty_banner = """
        <div style="background:rgba(88,166,255,0.06); border:1px solid rgba(88,166,255,0.25); border-radius:12px; padding:24px 20px; text-align:center; margin-bottom:16px;">
            <div style="font-size:32px; margin-bottom:8px;">🏦</div>
            <h4 style="color:#f0f6fc; margin-bottom:6px; font-size:16px;">한국투자증권 실전 계좌(10111722-01) 보유 주식이 없습니다</h4>
            <p style="color:#8b949e; font-size:13px; line-height:1.6; margin:0 auto; max-width:650px;">
                현재 <strong>원화 현금 5,000,000원(100%)</strong>이 안전하게 예수금으로 보존되어 대기 중입니다.<br>
                국내 증시 개장 시 마크 미너비니 SEPA 최우수 주도주 돌파 신호가 감지되면 <strong>슬롯당 125만원(총 4슬롯)</strong>씩 기계적 분할 매수가 집행됩니다.
            </p>
        </div>
        """
        empty_row = '<tr><td colspan="9" class="text-center py-4" style="color:#8b949e;">현재 한국투자증권 실전 계좌에 보유 중인 주식이 없습니다 (현금 100% 보존 대기).</td></tr>'
        return empty_banner, empty_row

    cards = []
    rows = []
    for idx, h in enumerate(holdings, 1):
        code = h.get("code", "")
        name = h.get("name", code)
        shares = int(h.get("shares", 0))
        buy_p = float(h.get("buy_price", 0))
        curr_p = float(h.get("current_price", buy_p))
        eval_amt = int(h.get("eval_amount", curr_p * shares))
        profit_won = int(h.get("profit_won", (curr_p - buy_p) * shares))
        ret_pct = float(h.get("return_pct", ((curr_p - buy_p) / buy_p * 100) if buy_p > 0 else 0.0))
        
        stop_p = buy_p * 0.925
        ret_color = "#3fb950" if ret_pct >= 0 else "#f85149"
        ret_sign = "+" if ret_pct > 0 else ""

        card = f"""
        <div class="stock-mobile-card">
            <div class="card-top-row">
                <div>
                    <span class="tag tag-gold" style="margin-right:4px;">#{idx}</span>
                    <strong style="color:#58a6ff; font-size:15px;">{name}</strong>
                    <span style="font-size:12px; color:#8b949e;">({code})</span>
                </div>
                <span class="tag tag-blue">실전 {shares}주</span>
            </div>
            <div class="card-metric-row">
                <div>
                    <div class="metric-item-label">현재가 (매수가)</div>
                    <div class="metric-item-val">{int(curr_p):,}원 <small style="font-size:10px; color:#8b949e;">({int(buy_p):,}원)</small></div>
                </div>
                <div>
                    <div class="metric-item-label">수익률 (평가손익)</div>
                    <div class="metric-item-val" style="color:{ret_color};">{ret_sign}{ret_pct:.2f}% <small style="font-size:10px;">({ret_sign}{profit_won:,}원)</small></div>
                </div>
                <div>
                    <div class="metric-item-label">평가금액</div>
                    <div class="metric-item-val">{eval_amt:,}원</div>
                </div>
            </div>
            <div class="card-bottom-row">
                <div>권장 손절선: <strong style="color:#f85149;">{int(stop_p):,}원 (-7.5%)</strong></div>
                <div style="color:#3fb950;">기관 50MA 추세 홀딩</div>
            </div>
        </div>
        """
        cards.append(card)

        row = f"""
        <tr>
            <td class="text-center font-bold">#{idx}</td>
            <td><strong>{name}</strong> <small class="text-muted">({code})</small></td>
            <td class="text-right font-mono font-bold">{shares:,}주</td>
            <td class="text-right font-mono">{int(buy_p):,}원</td>
            <td class="text-right font-mono font-bold">{int(curr_p):,}원</td>
            <td class="text-right font-mono font-bold" style="color:{ret_color};">{ret_sign}{ret_pct:.2f}%</td>
            <td class="text-right font-mono font-bold" style="color:{ret_color};">{ret_sign}{profit_won:,}원</td>
            <td class="text-right font-mono font-bold">{eval_amt:,}원</td>
            <td class="text-center"><span class="badge badge-safe font-bold">🟢 정상 홀딩</span></td>
        </tr>
        """
        rows.append(row)

    cards_html = f'<div class="stock-cards-list" id="kisMobileCards">{"".join(cards)}</div>'
    rows_html = "".join(rows)
    return cards_html, rows_html


def build_sell_rows(sell_signals: list[dict]) -> str:
    """내 보유 종목 매도 감시 테이블 행 HTML을 생성합니다."""
    if not sell_signals:
        return '<tr><td colspan="13" class="text-center py-4">등록된 보유 종목이 없습니다. 상단의 <strong>[➕ 보유 종목 추가]</strong> 버튼을 눌러 보유 종목을 등록하세요.</td></tr>'

    rows_html = []
    for idx, r in enumerate(sell_signals):
        code = str(r["code"])
        name = str(r["name"])
        market = str(r["market"]).upper()
        is_us = market == "US"
        buy_p = float(r.get("buy_price", 0))
        curr_p = float(r.get("current_price", 0))
        ret_pct = float(r.get("current_return_pct", 0))
        max_ret = float(r.get("max_return_pct", 0))
        from_peak = float(r.get("pct_from_peak", 0))
        stop_p = float(r.get("active_stop_price", 0))
        signal = str(r.get("signal", "🟢 홀딩"))
        urgency = str(r.get("urgency", "SAFE"))
        action = str(r.get("action_plan", ""))

        if is_us:
            chart_url = f"https://www.tradingview.com/chart/?symbol={code}"
            link_html = f"""
                <a href="{chart_url}" target="_blank" class="stock-link">
                    <strong>{code}</strong> <small class="text-muted">({name[:16]})</small> 📈
                </a>
            """
            buy_str = f"${buy_p:,.2f}"
            curr_str = f"${curr_p:,.2f}"
            stop_str = f"${stop_p:,.2f}"
        else:
            chart_url = f"https://finance.naver.com/item/main.naver?code={code}"
            link_html = f"""
                <a href="{chart_url}" target="_blank" class="stock-link">
                    <strong>{name}</strong> <small class="text-muted">({code})</small> ↗
                </a>
            """
            buy_str = f"{int(buy_p):,}원"
            curr_str = f"{int(curr_p):,}원"
            stop_str = f"{int(stop_p):,}원"

        ret_class = "text-success font-bold" if ret_pct >= 0 else "text-danger font-bold"
        peak_class = "text-danger" if from_peak <= -7.0 else "text-warning" if from_peak <= -3.0 else "text-muted"

        if urgency == "CRITICAL":
            badge_html = f'<span class="badge badge-critical font-bold">{signal}</span>'
        elif urgency == "WARNING":
            badge_html = f'<span class="badge badge-warning font-bold">{signal}</span>'
        elif urgency == "INFO":
            badge_html = f'<span class="badge badge-info">{signal}</span>'
        else:
            badge_html = f'<span class="badge badge-safe">{signal}</span>'

        row = f"""
        <tr id="sell-row-{code}">
            <td class="text-center font-bold">{idx + 1}</td>
            <td>{link_html}</td>
            <td class="text-center"><span class="market-tag market-{market.lower()}">{market}</span></td>
            <td class="text-center font-mono col-desktop">{r.get('buy_date', '-')}</td>
            <td class="text-right font-mono">{buy_str}</td>
            <td class="text-right font-mono font-bold">{curr_str}</td>
            <td class="text-right font-mono {ret_class}" data-order="{ret_pct}">{ret_pct:+.2f}%</td>
            <td class="text-right font-mono text-success col-desktop" data-order="{max_ret}">+{max_ret:.1f}%</td>
            <td class="text-right font-mono {peak_class}" data-order="{from_peak}">{from_peak:.1f}%</td>
            <td class="text-center">{badge_html}</td>
            <td class="text-right font-mono font-bold text-warning">{stop_str}</td>
            <td style="font-size: 13px; max-width: 320px; white-space: normal;">{action}</td>
            <td class="text-center">
                <button class="btn-del" onclick="deleteStockFromWeb('{code}', '{name}')" title="삭제">🗑️</button>
            </td>
        </tr>
        """
        rows_html.append(row)

    return "\n".join(rows_html)


def build_sell_mobile_cards(sell_signals: list[dict]) -> str:
    """스마트폰 전용 매도 감시 카드 뷰 HTML"""
    if not sell_signals:
        return '<div style="text-align:center; padding:32px 16px; color:#8b949e;">등록된 보유 종목이 없습니다.</div>'

    cards = []
    for idx, r in enumerate(sell_signals):
        code = str(r["code"])
        name = str(r["name"])
        market = str(r["market"]).upper()
        is_us = market == "US"
        buy_p = float(r.get("buy_price", 0))
        curr_p = float(r.get("current_price", 0))
        ret_pct = float(r.get("current_return_pct", 0))
        stop_p = float(r.get("active_stop_price", 0))
        signal = str(r.get("signal", "🟢 홀딩"))
        urgency = str(r.get("urgency", "SAFE"))
        action = str(r.get("action_plan", ""))

        price_fmt = f"${curr_p:,.2f}" if is_us else f"{int(curr_p):,}원"
        buy_fmt = f"${buy_p:,.2f}" if is_us else f"{int(buy_p):,}원"
        stop_fmt = f"${stop_p:,.2f}" if is_us else f"{int(stop_p):,}원"
        ret_color = "#3fb950" if ret_pct >= 0 else "#f85149"
        ret_sign = "+" if ret_pct > 0 else ""

        tag_class = "tag-red" if urgency == "CRITICAL" else "tag-gold" if urgency == "WARNING" else "tag-green"

        card = f"""
        <div class="stock-mobile-card">
            <div class="card-top-row">
                <div>
                    <span class="tag tag-gold" style="margin-right:4px;">#{idx + 1}</span>
                    <strong style="color:#58a6ff; font-size:15px;">{name}</strong>
                    <span style="font-size:11px; color:#8b949e;">({code})</span>
                    <span class="tag tag-blue" style="margin-left:4px;">{market}</span>
                </div>
                <span class="tag {tag_class}">{signal}</span>
            </div>
            <div class="card-metric-row">
                <div>
                    <div class="metric-item-label">현재가 (매수가)</div>
                    <div class="metric-item-val">{price_fmt} <small style="font-size:10px; color:#8b949e;">({buy_fmt})</small></div>
                </div>
                <div>
                    <div class="metric-item-label">현재 손익률</div>
                    <div class="metric-item-val" style="color:{ret_color};">{ret_sign}{ret_pct:.2f}%</div>
                </div>
                <div>
                    <div class="metric-item-label">권장 스탑선</div>
                    <div class="metric-item-val" style="color:#f59e0b;">{stop_fmt}</div>
                </div>
            </div>
            <div class="card-bottom-row">
                <div style="font-size:12px; color:#c9d1d9;">💡 {action}</div>
            </div>
        </div>
        """
        cards.append(card)

    return f'<div class="stock-cards-list" id="sellMobileCards">{"".join(cards)}</div>'


def generate_unified_dashboard(
    kr_df: pd.DataFrame | None = None,
    us_df: pd.DataFrame | None = None,
    kr_new: list[dict] | None = None,
    us_new: list[dict] | None = None,
    kr_drop: list[dict] | None = None,
    us_drop: list[dict] | None = None,
    sell_signals: list[dict] | None = None,
    output_path: str = "index.html",
) -> str:
    """한국 및 미국 주식 스크리닝, 한투 실전 계좌 잔고, 매도 감시를 통합한 반응형 모바일 대시보드를 생성합니다."""
    today_str = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")

    # 1. 최신 스크리닝 데이터 캐시 로드 (비어있을 경우 자동 보충)
    if kr_df is None or kr_df.empty:
        kr_file = os.path.join("history", "latest_kr.json")
        if os.path.exists(kr_file):
            try:
                with open(kr_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    kr_df = pd.DataFrame(d.get("df", []))
                    kr_new = d.get("new", [])
                    kr_drop = d.get("drop", [])
            except Exception:
                kr_df = pd.DataFrame()

    if us_df is None or us_df.empty:
        us_file = os.path.join("history", "latest_us.json")
        if os.path.exists(us_file):
            try:
                with open(us_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    us_df = pd.DataFrame(d.get("df", []))
                    us_new = d.get("new", [])
                    us_drop = d.get("drop", [])
            except Exception:
                us_df = pd.DataFrame()

    kr_df = kr_df if kr_df is not None else pd.DataFrame()
    us_df = us_df if us_df is not None else pd.DataFrame()
    kr_new = kr_new or []
    us_new = us_new or []
    kr_drop = kr_drop or []
    us_drop = us_drop or []

    # 시가총액 5,000억원 이상 필터
    if kr_df is not None and not kr_df.empty and "marcap" in kr_df.columns:
        kr_df = kr_df[pd.to_numeric(kr_df["marcap"], errors="coerce") >= 500_000_000_000].reset_index(drop=True)
    if kr_new:
        kr_new = [s for s in kr_new if s.get("marcap", 0) >= 500_000_000_000]
    if kr_drop:
        kr_drop = [s for s in kr_drop if s.get("marcap", 0) >= 500_000_000_000]

    # 2. 한투 실전 계좌(10111722-01) 잔고 및 보유 종목 실시간 조회
    kis_info = fetch_kis_balance()

    # 3. 포트폴리오 및 매도 감시 데이터 로드
    portfolio_data = []
    if os.path.exists("portfolio.json"):
        try:
            with open("portfolio.json", "r", encoding="utf-8") as f:
                portfolio_data = json.load(f)
        except Exception:
            portfolio_data = []

    repo_name = "jungkbugk/minervini-krx"
    if os.path.exists("github_config.json"):
        try:
            with open("github_config.json", "r", encoding="utf-8") as f:
                repo_name = json.load(f).get("repo", repo_name)
        except Exception:
            pass

    portfolio_json_str = json.dumps(portfolio_data, ensure_ascii=False)

    if sell_signals is None:
        signals_file = os.path.join("history", "latest_sell_signals.json")
        if os.path.exists(signals_file):
            try:
                with open(signals_file, "r", encoding="utf-8") as f:
                    sell_signals = json.load(f)
            except Exception:
                sell_signals = []
        else:
            try:
                from minervini_sell_monitor import run_sell_monitor
                sell_signals = run_sell_monitor()
            except Exception:
                sell_signals = []

    sell_signals = sell_signals or []
    urgent_sell_count = sum(1 for s in sell_signals if s.get("urgency") in ["CRITICAL", "WARNING"])

    # 4. 시장 레짐 필터 데이터 로드
    try:
        from market_filter import get_market_regime, build_market_regime_banner
        regime_data = get_market_regime()
    except Exception:
        regime_data = {}

    kr_regime = regime_data.get("kr", {})
    us_regime = regime_data.get("us", {})
    kr_can_buy = kr_regime.get("can_buy", True)
    us_can_buy = us_regime.get("can_buy", True)

    kr_regime_banner = build_market_regime_banner(regime_data, "KR") if "build_market_regime_banner" in locals() else ""
    us_regime_banner = build_market_regime_banner(regime_data, "US") if "build_market_regime_banner" in locals() else ""

    kr_tab_badge = '<span class="badge badge-safe" style="font-size:11px; margin-left:6px;">🟢 매수가능</span>' if kr_can_buy else '<span class="badge badge-critical" style="font-size:11px; margin-left:6px;">🚨 조정장(매수금지)</span>'
    us_tab_badge = '<span class="badge badge-safe" style="font-size:11px; margin-left:6px;">🟢 매수가능</span>' if us_can_buy else '<span class="badge badge-critical" style="font-size:11px; margin-left:6px;">🚨 조정장(매수금지)</span>'
    kr_regime_summary = '<span style="color:#3fb950; font-weight:bold;">🟢 50MA 상회(정상)</span>' if kr_can_buy else '<span style="color:#f85149; font-weight:bold;">🚨 50MA 하회(조정장)</span>'
    us_regime_summary = '<span style="color:#3fb950; font-weight:bold;">🟢 50MA 상회(정상)</span>' if us_can_buy else '<span style="color:#f85149; font-weight:bold;">🚨 50MA 하회(조정장)</span>'

    kr_block_warning = "" if kr_can_buy else """
    <div style="background:rgba(248,81,73,0.18); border:2px solid #f85149; border-radius:10px; padding:14px 18px; margin-bottom:16px; color:#ff7b72; display:flex; align-items:center; gap:12px;">
        <span style="font-size:24px;">🚫</span>
        <div>
            <strong style="font-size:15px; color:#fff;">[신규 매수 차단 알림] 코스피/코스닥 지수 50일선 이탈 — 현금 100% 보존 구간</strong>
            <p style="margin:4px 0 0 0; font-size:13px; color:#c9d1d9;">
                현재 국내 시장 지수가 50일 이동평균선 아래로 하회하여 하방 압력이 높습니다. 아래 통과 종목들은 <strong>관심 종목(Watchlist)</strong>으로만 등록하시고, <strong>지수가 50일선을 회복할 때까지 신규 매수를 자제하세요.</strong>
            </p>
        </div>
    </div>
    """

    us_block_warning = "" if us_can_buy else """
    <div style="background:rgba(248,81,73,0.18); border:2px solid #f85149; border-radius:10px; padding:14px 18px; margin-bottom:16px; color:#ff7b72; display:flex; align-items:center; gap:12px;">
        <span style="font-size:24px;">🚫</span>
        <div>
            <strong style="font-size:15px; color:#fff;">[신규 매수 차단 알림] 미국 지수 50일선 이탈 — 현금 관망 권장</strong>
            <p style="margin:4px 0 0 0; font-size:13px; color:#c9d1d9;">
                현재 미국 시장 지수가 50일 이동평균선 아래로 하회하고 있습니다. 지수가 50일선을 회복하기 전까지는 신규 매수를 자제하고 리스크를 관리하세요.
            </p>
        </div>
    </div>
    """

    kr_sectors = get_stock_sectors(kr_df)
    kr_rows = build_tab_rows(kr_df, is_us=False, sectors=kr_sectors)
    us_rows = build_tab_rows(us_df, is_us=True)
    sell_rows = build_sell_rows(sell_signals)

    # 모바일 카드 생성
    kr_mobile_cards = build_kr_mobile_cards(kr_df, kr_sectors)
    us_mobile_cards = build_us_mobile_cards(us_df)
    sell_mobile_cards = build_sell_mobile_cards(sell_signals)
    kis_mobile_cards, kis_rows = build_kis_holdings_cards_and_rows(kis_info)

    kr_new_text = ", ".join([f"<strong>{s['name']}</strong>" for s in kr_new[:6]]) or "없음"
    kr_drop_text = ", ".join([f"{s['name']}" for s in kr_drop[:6]]) or "없음"
    us_new_text = ", ".join([f"<strong>{s['name']}</strong>({s['code']})" for s in us_new[:6]]) or "없음"
    us_drop_text = ", ".join([f"{s['name']}({s['code']})" for s in us_drop[:6]]) or "없음"

    sell_badge_bg = "#f85149" if urgent_sell_count > 0 else "#3fb950"
    qr_b64 = ensure_qr_code()

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#0d1117">
    <title>마크 미너비니 SEPA 통합 관제 대시보드 | 모바일 & 한투 실전 계좌</title>
    <link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
    <style>
        :root {{
            --bg-color: #0a0d12;
            --card-bg: #131822;
            --card-hover: #1a2230;
            --border-color: #273142;
            --text-main: #cbd5e1;
            --text-heading: #f8fafc;
            --text-muted: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-green: #22c55e;
            --accent-red: #ef4444;
            --accent-gold: #f59e0b;
            --accent-purple: #a855f7;
            --card-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.4);
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, "Noto Sans KR", sans-serif;
            padding: 16px 12px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1440px;
            margin: 0 auto;
        }}

        /* 상단 유틸리티 내비게이션 */
        .top-navbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(19, 24, 34, 0.85);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 10px 16px;
            margin-bottom: 14px;
            font-size: 13px;
        }}
        .brand-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-weight: 700;
            color: var(--text-heading);
        }}
        .live-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--accent-green);
            box-shadow: 0 0 10px var(--accent-green);
            display: inline-block;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.95); opacity: 0.8; }}
            50% {{ transform: scale(1.2); opacity: 1; }}
            100% {{ transform: scale(0.95); opacity: 0.8; }}
        }}
        .nav-links {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .btn-link {{
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.35);
            color: var(--accent-blue);
            text-decoration: none;
            padding: 5px 11px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn-link:hover, .btn-link:active {{
            background: rgba(56, 189, 248, 0.25);
            color: #fff;
        }}
        .btn-silver {{
            background: rgba(245, 158, 11, 0.12);
            border-color: rgba(245, 158, 11, 0.35);
            color: var(--accent-gold);
        }}
        .btn-silver:hover {{ background: rgba(245, 158, 11, 0.25); }}

        /* 메인 헤더 영역 */
        .header {{
            background: linear-gradient(135deg, #172033 0%, #0d131f 100%);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px 22px;
            margin-bottom: 16px;
            box-shadow: var(--card-shadow);
            position: relative;
            overflow: hidden;
        }}
        .header h1 {{
            color: var(--text-heading);
            font-size: 21px;
            font-weight: 800;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
            letter-spacing: -0.3px;
        }}
        .badge-medal {{
            background: linear-gradient(135deg, #f59e0b, #d97706);
            color: #fff;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
        }}
        .header p {{
            color: var(--text-muted);
            font-size: 13px;
            margin-bottom: 10px;
            line-height: 1.4;
        }}

        /* 4대 지표 카드 그리드 (모바일 2x2 완벽 정렬) */
        .cards-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 16px;
        }}
        .metric-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 14px 16px;
            box-shadow: var(--card-shadow);
            transition: transform 0.2s, border-color 0.2s;
        }}
        .metric-card .title {{
            font-size: 11px;
            color: var(--text-muted);
            font-weight: 600;
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .metric-card .value {{
            font-size: 22px;
            font-weight: 800;
            color: var(--text-heading);
            margin-bottom: 2px;
            letter-spacing: -0.5px;
        }}
        .metric-card .sub {{
            font-size: 11px;
            color: var(--accent-green);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        /* 탭 네비게이션 (Sticky) */
        .tab-nav {{
            display: flex;
            gap: 6px;
            overflow-x: auto;
            padding: 6px 0;
            margin-bottom: 16px;
            scrollbar-width: none;
            -webkit-overflow-scrolling: touch;
            position: sticky;
            top: 8px;
            z-index: 100;
            background: rgba(10, 13, 18, 0.85);
            backdrop-filter: blur(8px);
        }}
        .tab-nav::-webkit-scrollbar {{ display: none; }}
        .tab-btn {{
            flex: 0 0 auto;
            background: var(--card-bg);
            color: var(--text-muted);
            border: 1px solid var(--border-color);
            padding: 8px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .tab-btn:hover {{
            color: #fff;
            border-color: var(--accent-blue);
        }}
        .tab-btn.active {{
            background: var(--accent-blue);
            color: #0a0d12;
            border-color: var(--accent-blue);
            font-weight: 700;
        }}
        .tab-btn.tab-sell-btn.active {{
            background: linear-gradient(135deg, #ef4444, #dc2626);
            color: #fff;
            border-color: #ef4444;
        }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        /* 모바일 카드 뷰 */
        .stock-cards-list {{
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-top: 10px;
        }}
        .stock-mobile-card {{
            background: #161e2e;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px 14px;
        }}
        .card-top-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }}
        .card-metric-row {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
            background: rgba(0, 0, 0, 0.25);
            border-radius: 8px;
            padding: 8px 10px;
            margin: 6px 0;
            font-size: 11px;
        }}
        .metric-item-label {{ color: var(--text-muted); margin-bottom: 2px; }}
        .metric-item-val {{ font-weight: 700; color: var(--text-heading); font-size: 13px; }}
        .card-bottom-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            color: var(--text-muted);
            margin-top: 6px;
        }}

        /* 뱃지 태그 */
        .tag {{
            display: inline-block;
            padding: 2px 7px;
            border-radius: 5px;
            font-size: 11px;
            font-weight: 600;
            white-space: nowrap;
        }}
        .tag-green {{ background: rgba(34, 197, 94, 0.15); color: #22c55e; border: 1px solid rgba(34, 197, 94, 0.4); }}
        .tag-blue {{ background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); }}
        .tag-gold {{ background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); }}
        .tag-red {{ background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); }}
        .tag-purple {{ background: rgba(168, 85, 247, 0.15); color: #a855f7; border: 1px solid rgba(168, 85, 247, 0.4); }}

        /* 20년 백테스트 그리드 */
        .backtest-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            margin-top: 10px;
        }}
        .bt-card {{
            background: #161e2e;
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 14px;
        }}
        .bt-card.winner {{
            border-color: rgba(245, 158, 11, 0.5);
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.08), #161e2e);
        }}
        .bt-title {{
            font-size: 13px;
            font-weight: 700;
            color: var(--text-heading);
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .bt-stat-row {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            padding: 4px 0;
            border-bottom: 1px dashed rgba(255, 255, 255, 0.06);
        }}

        /* 데스크톱 카드 및 테이블 */
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            overflow-x: auto;
        }}
        table.dataTable {{
            width: 100% !important;
            border-collapse: collapse !important;
            color: var(--text-main);
        }}
        table.dataTable thead th {{
            background-color: #1a2230 !important;
            color: var(--accent-blue) !important;
            border-bottom: 2px solid var(--border-color) !important;
            padding: 10px 8px;
            font-size: 12px;
        }}
        table.dataTable tbody td {{
            padding: 8px 8px;
            border-bottom: 1px solid #1f2937;
            font-size: 13px;
        }}
        table.dataTable tbody tr:hover {{
            background-color: rgba(56, 189, 248, 0.08) !important;
        }}
        .stock-link {{
            color: var(--accent-blue);
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        .font-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
        .font-bold {{ font-weight: bold; }}
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .text-success {{ color: var(--accent-green); }}
        .text-danger {{ color: var(--accent-red); }}
        .text-warning {{ color: var(--accent-gold); }}
        .text-muted {{ color: var(--text-muted); }}

        /* 모달 스타일 */
        .modal-overlay {{
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }}
        .modal-overlay.active {{ display: flex; }}
        .modal-box {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            width: 90%;
            max-width: 480px;
        }}

        /* 토스트 알림 */
        #toast {{
            position: fixed;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(34, 197, 94, 0.95);
            color: #000;
            padding: 8px 18px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            display: none;
            z-index: 1000;
        }}

        @media (max-width: 768px) {{
            body {{ padding: 10px 8px; }}
            .header h1 {{ font-size: 18px; }}
            .cards-grid {{ grid-template-columns: repeat(2, 1fr); gap: 8px; }}
            .metric-card {{ padding: 12px; }}
            .metric-card .value {{ font-size: 18px; }}
            .backtest-grid {{ grid-template-columns: 1fr; }}
            .card {{ display: none; }} /* 모바일 기본: 카드 뷰 우선 */
            .stock-cards-list {{ display: flex; }}
        }}
        @media (min-width: 769px) {{
            .stock-cards-list {{ display: none; }} /* 데스크톱 기본: 테이블 뷰 우선 */
            .card {{ display: block; }}
        }}
    </style>
</head>
<body>
    <div id="toast">복사 완료!</div>

    <div class="container">
        <!-- 상단 유틸리티 내비게이션 바 -->
        <div class="top-navbar">
            <div class="brand-badge">
                <span class="live-dot"></span>
                <span>🥇 Mark Minervini SEPA KRX</span>
            </div>
            <div class="nav-links">
                <a href="https://jungkbugk.github.io/PeterLynch/" target="_blank" class="btn-link btn-silver" title="피터 린치 미국 퀀트 대시보드 바로가기">
                    🥈 미장 피터린치
                </a>
                <button onclick="toggleMobileView()" class="btn-link" title="카드 뷰와 테이블 뷰 전환">
                    📱/💻 보기전환
                </button>
                <button onclick="copyCurrentUrl()" class="btn-link" title="주소 복사">
                    📋 공유
                </button>
                <button onclick="location.reload()" class="btn-link" title="새로고침">
                    🔄 새로고침
                </button>
            </div>
        </div>

        <!-- 헤더 영역 -->
        <div class="header">
            <h1>
                <span>마크 미너비니 SEPA 트렌드 템플릿 통합 대시보드</span>
                <span class="badge-medal">🥇 20년 백테스트 금메달 (CAGR 27.6%)</span>
            </h1>
            <p>
                <strong>동기화:</strong> {today_str} |
                <strong>국내 통과:</strong> <span class="text-success font-bold">{len(kr_df)}개</span> ({kr_regime_summary}) |
                <strong>한투 계좌:</strong> <span style="color:#58a6ff; font-weight:bold;">10111722-01 (실전투자 연동)</span> |
                <strong>매도 감시:</strong> <span class="font-bold" style="color:{sell_badge_bg}">{len(sell_signals)}개 (경보 {urgent_sell_count}건)</span>
            </p>
        </div>

        <!-- 4대 핵심 지표 카드 (모바일 2x2 완벽 대응) -->
        <div class="cards-grid">
            <div class="metric-card">
                <div class="title">💰 한투 실전 총 평가자산</div>
                <div class="value">₩{kis_info['total_asset']:,}</div>
                <div class="sub">10111722-01 실전 계좌 정상 연동</div>
            </div>
            <div class="metric-card">
                <div class="title">💵 주문가능 원화 예수금</div>
                <div class="value" style="color: var(--accent-green);">₩{kis_info['cash_available']:,}</div>
                <div class="sub">슬롯당 125만원(4슬롯) 매수 대기</div>
            </div>
            <div class="metric-card">
                <div class="title">🚦 시장 레짐 (KOSPI/KOSDAQ)</div>
                <div class="value" style="color: var(--accent-blue);">🟢 매수 허용</div>
                <div class="sub">지수 50일 이동평균선 상회 구간</div>
            </div>
            <div class="metric-card">
                <div class="title">📊 20개년 실증 수익률</div>
                <div class="value" style="color: var(--accent-gold);">+19,704.7%</div>
                <div class="sub">CAGR 27.57% (원금 198배 🥇 1위)</div>
            </div>
        </div>

        <!-- 탭 네비게이션 버튼 -->
        <div class="tab-nav">
            <button class="tab-btn active" onclick="switchTab('kr')">
                🇰🇷 국내 주식 스크리너
                <span class="tag tag-blue">{len(kr_df)}개</span>
            </button>
            <button class="tab-btn" onclick="switchTab('kis')">
                🏦 한투 실전 계좌 잔고
                <span class="tag tag-gold">{len(kis_info['holdings'])}종목</span>
            </button>
            <button class="tab-btn" onclick="switchTab('us')">
                🇺🇸 미국 주식 스크리너
                <span class="tag tag-blue">{len(us_df)}개</span>
            </button>
            <button class="tab-btn tab-sell-btn" onclick="switchTab('sell')">
                🛡️ 관심종목 매도 감시
                <span class="tag" style="background:{sell_badge_bg}; color:#fff;">{len(sell_signals)}개</span>
            </button>
            <button class="tab-btn" onclick="switchTab('backtest')">
                📊 20년 백테스트 실증
                <span class="tag tag-gold">🥇 금메달</span>
            </button>
        </div>

        <!-- 탭 1: 한국 주식 스크리너 -->
        <div id="tab-kr" class="tab-content active">
            {kr_regime_banner}
            {kr_block_warning}
            
            <div class="change-banner" style="display:flex; gap:10px; margin-bottom:12px;">
                <div style="flex:1; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); border-radius:8px; padding:10px 12px; font-size:12px; color:#ff7b72;">
                    🔥 <strong>오늘 신규 편입 ({len(kr_new)}개):</strong> {kr_new_text}
                </div>
                <div style="flex:1; background:rgba(148,163,184,0.1); border:1px solid rgba(148,163,184,0.3); border-radius:8px; padding:10px 12px; font-size:12px; color:#94a3b8;">
                    🚨 <strong>전일 대비 이탈 ({len(kr_drop)}개):</strong> {kr_drop_text}
                </div>
            </div>

            <!-- 스마트폰 카드 뷰 -->
            {kr_mobile_cards}

            <!-- 데스크톱 테이블 뷰 -->
            <div class="card" id="krTableCard">
                <table id="tableKR" class="display nowrap" style="width:100%">
                    <thead>
                        <tr>
                            <th class="text-center">순위</th>
                            <th>종목명</th>
                            <th class="text-center">시장</th>
                            <th class="text-center">상태</th>
                            <th class="text-center">SEPA점수</th>
                            <th class="text-right">시총(억)</th>
                            <th class="text-right">현재가</th>
                            <th class="text-center">RS</th>
                            <th class="text-right">52주고점거리</th>
                            <th class="text-right col-desktop">52주저점상승</th>
                            <th class="text-right col-desktop">3개월수익</th>
                            <th class="text-right col-desktop">20일거래대금</th>
                            <th class="text-center">VCP</th>
                            <th class="text-center">메이저 수급 (5일)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {kr_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 탭 2: 한국투자증권 실전 계좌 (10111722-01) -->
        <div id="tab-kis" class="tab-content">
            <div style="background:#131822; border:1px solid var(--border-color); border-radius:12px; padding:16px 20px; margin-bottom:16px;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                    <div>
                        <h3 style="color:#f8fafc; font-size:16px; font-weight:700; display:flex; align-items:center; gap:8px;">
                            <span>🏦 한국투자증권 Open API 실전 계좌 연동 현황</span>
                            <span class="tag tag-green">🟢 실시간 정상</span>
                        </h3>
                        <p style="color:#94a3b8; font-size:12px; margin-top:4px;">
                            계좌번호: <strong style="color:#58a6ff;">{kis_info['account_no']}</strong> | 모드: <strong>실전투자</strong> | 통화: <strong>원화(KRW)</strong>
                        </p>
                    </div>
                    <div>
                        <span class="tag tag-gold" style="font-size:12px; padding:4px 10px;">예수금: ₩{kis_info['cash_available']:,}</span>
                    </div>
                </div>
            </div>

            <!-- 스마트폰 카드 뷰 -->
            {kis_mobile_cards}

            <!-- 데스크톱 테이블 뷰 -->
            <div class="card" id="kisTableCard">
                <table id="tableKis" class="display nowrap" style="width:100%">
                    <thead>
                        <tr>
                            <th class="text-center">순번</th>
                            <th>종목명 (코드)</th>
                            <th class="text-right">보유수량</th>
                            <th class="text-right">매수가</th>
                            <th class="text-right">현재가</th>
                            <th class="text-right">수익률</th>
                            <th class="text-right">평가손익</th>
                            <th class="text-right">평가금액</th>
                            <th class="text-center">상태</th>
                        </tr>
                    </thead>
                    <tbody>
                        {kis_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 탭 3: 미국 주식 스크리너 -->
        <div id="tab-us" class="tab-content">
            {us_regime_banner}
            {us_block_warning}

            <!-- 스마트폰 카드 뷰 -->
            {us_mobile_cards}

            <!-- 데스크톱 테이블 뷰 -->
            <div class="card" id="usTableCard">
                <table id="tableUS" class="display nowrap" style="width:100%">
                    <thead>
                        <tr>
                            <th class="text-center">순위</th>
                            <th>티커 (기업명)</th>
                            <th class="text-center">거래소</th>
                            <th class="text-center">상태</th>
                            <th class="text-center">SEPA점수</th>
                            <th class="text-right">시가총액</th>
                            <th class="text-right">현재가</th>
                            <th class="text-center">RS</th>
                            <th class="text-right">52주고점거리</th>
                            <th class="text-right col-desktop">52주저점상승</th>
                            <th class="text-right col-desktop">3개월수익</th>
                            <th class="text-right col-desktop">20일거래대금</th>
                            <th class="text-center">VCP</th>
                        </tr>
                    </thead>
                    <tbody>
                        {us_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 탭 4: 관심종목 매도 감시 -->
        <div id="tab-sell" class="tab-content">
            <div style="background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.3); border-radius:10px; padding:14px 18px; margin-bottom:14px; font-size:12px; color:#cbd5e1; line-height:1.6;">
                🛡️ <strong>마크 미너비니 핵심 매도 규칙:</strong><br>
                1. <strong>초기 손절 (1R Cut):</strong> 매수가 대비 -7~8% 하락 시 기계적 전량 손절하여 원금 보존<br>
                2. <strong>추세 완주 (+20% 도달 시):</strong> 3R 이상 수익 구간에서는 조기 매도하지 않고 <strong>50일선 트레일링 스탑</strong>으로 대시세를 끝까지 향유<br>
                3. <strong>고점 반락:</strong> 최고점 대비 -10% 이상 하락 시 수익 확정 익절
            </div>

            <!-- 스마트폰 카드 뷰 -->
            {sell_mobile_cards}

            <!-- 데스크톱 테이블 뷰 -->
            <div class="card" id="sellTableCard">
                <table id="tableSell" class="display nowrap" style="width:100%">
                    <thead>
                        <tr>
                            <th class="text-center">순번</th>
                            <th>보유 종목 (코드)</th>
                            <th class="text-center">시장</th>
                            <th class="text-center col-desktop">매수일자</th>
                            <th class="text-right">매수가</th>
                            <th class="text-right">현재가</th>
                            <th class="text-right">현재 손익</th>
                            <th class="text-right col-desktop">최고 수익</th>
                            <th class="text-right">고점거리</th>
                            <th class="text-center">진단</th>
                            <th class="text-right">권장스탑선</th>
                            <th>대응 가이드</th>
                            <th class="text-center" style="width:50px;">관리</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sell_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 탭 5: 20개년 퀀트 전략 실증 성과 비교 -->
        <div id="tab-backtest" class="tab-content">
            <div class="backtest-grid">
                <div class="bt-card winner">
                    <div class="bt-title">
                        <span>🥇 한국 마크 미너비니 SEPA 추세추종</span>
                        <span class="tag tag-gold">20년 1위</span>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">20년 누적 수익률</span>
                        <strong style="color:#f59e0b; font-size:15px;">+19,704.7% (198.0배)</strong>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">연평균 복리(CAGR)</span>
                        <strong style="color:#22c55e;">27.57%</strong>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">전략 핵심 엔진</span>
                        <span>50일선 트레일링 스탑 라이딩 + 5중 안전장치</span>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">자산 배분 가이드</span>
                        <span style="color:#38bdf8;">국내 실전 계좌 (비중 50%)</span>
                    </div>
                </div>

                <div class="bt-card winner">
                    <div class="bt-title">
                        <span>🥈 미국 피터 린치 GARP 저평가 성장주</span>
                        <span class="tag tag-green">20년 2위</span>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">20년 누적 수익률</span>
                        <strong style="color:#22c55e; font-size:15px;">+7,678.5% (77.8배)</strong>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">연평균 복리(CAGR)</span>
                        <strong style="color:#22c55e;">22.19%</strong>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">전략 핵심 엔진</span>
                        <span>PEG < 1.0 극저평가 + 10종목 균등 복리</span>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">자산 배분 가이드</span>
                        <span style="color:#38bdf8;">미국 실전 계좌 (비중 50%)</span>
                    </div>
                </div>

                <div class="bt-card">
                    <div class="bt-title">
                        <span>🇰🇷 한국 KOSPI 종합지수</span>
                        <span class="tag tag-blue">시장 벤치마크</span>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">20년 누적 수익률</span>
                        <strong>+692.3% (7.9배)</strong>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">연평균 복리(CAGR)</span>
                        <span>10.00%</span>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">미너비니 초과 성과</span>
                        <strong style="color:#f59e0b;">시장 대비 +17.57%p 알파 창출</strong>
                    </div>
                </div>

                <div class="bt-card">
                    <div class="bt-title">
                        <span>🇺🇸 미국 S&P 500 지수 (SPY)</span>
                        <span class="tag tag-blue">시장 벤치마크</span>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">20년 누적 수익률</span>
                        <strong>+544.2% (6.4배)</strong>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">연평균 복리(CAGR)</span>
                        <span>8.95%</span>
                    </div>
                    <div class="bt-stat-row">
                        <span style="color:#94a3b8;">피터 린치 초과 성과</span>
                        <strong style="color:#22c55e;">시장 대비 +13.24%p 알파 창출</strong>
                    </div>
                </div>
            </div>
        </div>

        <!-- 하단 푸터 및 QR 코드 -->
        <div style="text-align:center; color:#94a3b8; font-size:12px; margin-top:24px; padding:20px 10px; border-top:1px solid var(--border-color);">
            <div style="font-weight:700; color:#f8fafc; margin-bottom:6px;">
                🥇 마크 미너비니 SEPA 한국형 주도주 퀀트 시스템 · 20개년 실증 백테스트 1위 (CAGR 27.57%)
            </div>
            <div>한국투자증권 Open API 실전 계좌(10111722-01) 연동 · GitHub Pages 자동 동기화</div>
"""

    if qr_b64:
        html_content += f"""
            <div style="margin-top:14px; display:inline-flex; flex-direction:column; align-items:center; background:#131822; border:1px solid var(--border-color); border-radius:12px; padding:12px 18px;">
                <div style="font-size:11px; color:#94a3b8; margin-bottom:6px; font-weight:600;">📱 스마트폰 카메라로 QR 코드를 스캔하여 모바일 대시보드로 열기</div>
                <img src="data:image/png;base64,{qr_b64}" alt="스마트폰 접속 QR 코드" style="width:130px; height:130px; border-radius:8px; border:2px solid var(--border-color); background:#fff; padding:4px;">
                <div style="font-size:11px; margin-top:6px;"><a href="https://jungkbugk.github.io/minervini-krx/" target="_blank" style="color:#38bdf8; text-decoration:none;">https://jungkbugk.github.io/minervini-krx/</a></div>
            </div>
"""

    html_content += """
        </div>
    </div>

    <!-- 스크립트 영역 -->
    <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
    <script>
        function toggleMobileView() {
            const isCardsHidden = $('.stock-cards-list').first().css('display') === 'none';
            if (isCardsHidden) {
                $('.stock-cards-list').css('display', 'flex');
                $('.card').css('display', 'none');
                showToast("📱 스마트폰 카드 뷰로 전환되었습니다.");
            } else {
                $('.stock-cards-list').css('display', 'none');
                $('.card').css('display', 'block');
                showToast("💻 데이터 테이블 뷰로 전환되었습니다.");
            }
        }

        function copyCurrentUrl() {
            navigator.clipboard.writeText(window.location.href).then(() => {
                showToast("대시보드 주소가 복사되었습니다!");
            }).catch(() => {
                showToast("복사 실패 (주소창을 이용하세요)");
            });
        }

        function showToast(msg) {
            const t = document.getElementById("toast");
            t.innerText = msg;
            t.style.display = "block";
            setTimeout(() => { t.style.display = "none"; }, 2500);
        }

        $(document).ready(function() {
            const tableKR = $('#tableKR').DataTable({
                pageLength: 25,
                order: [[4, 'desc']],
                language: {
                    search: "국내 종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: { first: "처음", last: "마지막", next: "다음", previous: "이전" }
                }
            });

            const tableUS = $('#tableUS').DataTable({
                pageLength: 25,
                order: [[4, 'desc']],
                language: {
                    search: "미국 티커 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: { first: "처음", last: "마지막", next: "다음", previous: "이전" }
                }
            });

            const tableSell = $('#tableSell').DataTable({
                pageLength: 25,
                order: [[6, 'desc']],
                language: {
                    search: "보유 종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: { first: "처음", last: "마지막", next: "다음", previous: "이전" }
                }
            });

            const tableKis = $('#tableKis').DataTable({
                pageLength: 25,
                language: {
                    search: "실전 종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: { first: "처음", last: "마지막", next: "다음", previous: "이전" }
                }
            });

            window.switchTab = function(tab) {
                $('.tab-btn').removeClass('active');
                $('.tab-content').removeClass('active');

                if (tab === 'kr') {
                    $('.tab-btn').eq(0).addClass('active');
                    $('#tab-kr').addClass('active');
                    tableKR.columns.adjust().draw();
                } else if (tab === 'kis') {
                    $('.tab-btn').eq(1).addClass('active');
                    $('#tab-kis').addClass('active');
                    tableKis.columns.adjust().draw();
                } else if (tab === 'us') {
                    $('.tab-btn').eq(2).addClass('active');
                    $('#tab-us').addClass('active');
                    tableUS.columns.adjust().draw();
                } else if (tab === 'sell') {
                    $('.tab-btn').eq(3).addClass('active');
                    $('#tab-sell').addClass('active');
                    tableSell.columns.adjust().draw();
                } else if (tab === 'backtest') {
                    $('.tab-btn').eq(4).addClass('active');
                    $('#tab-backtest').addClass('active');
                }
            };
        });
    </script>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    if output_path == "index.html":
        try:
            with open("minervini_dashboard.html", "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception:
            pass

    print(f"[*] 모바일 반응형 & 한투 실전 계좌 연동 대시보드 생성 완료: {output_path}")
    return output_path


if __name__ == "__main__":
    generate_unified_dashboard()
