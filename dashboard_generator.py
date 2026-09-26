"""국내 주식(KR), 미국 주식(US), 그리고 마크 미너비니 포트폴리오 매도 감시(Sell Monitor) 3개 탭을 통합한 반응형 대시보드 생성기"""

from __future__ import annotations

from datetime import datetime
import json
import os
import pandas as pd


def format_kr_marcap(val: float | int) -> str:
    if pd.isna(val) or val <= 0: return "-"
    val = int(val)
    cho = val // 1_000_000_000_000
    eok = (val % 1_000_000_000_000) // 100_000_000
    if cho > 0:
        return f"{cho}조 {eok:,}억" if eok > 0 else f"{cho}조"
    return f"{eok:,}억"


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


def build_tab_rows(df: pd.DataFrame, is_us: bool = False) -> str:
    """각 시장별 매수 스크리닝 테이블 행 HTML을 생성합니다."""
    colspan = "13" if is_us else "14"
    if df.empty:
        return f'<tr><td colspan="{colspan}" class="text-center py-4">조건을 통과한 종목이 없습니다.</td></tr>'

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
            chart_url = f"https://finance.naver.com/item/main.naver?code={code}"
            link_html = f"""
                <a href="{chart_url}" target="_blank" class="stock-link">
                    <strong>{name}</strong> <small class="text-muted">({code})</small>
                    <span class="external-icon">↗</span>
                </a>
            """
            price_str = f"{int(r['close']):,}원"
            marcap_str = format_kr_marcap(r.get("marcap", 0))
            trading_val_str = f"{float(r.get('avg_trading_val_20d', 0)):.1f}억"

            # 국내 주식 스마트머니(외인/기관/투신/사모) 보조 지표 배지
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
            <td class="text-right text-success font-bold" data-order="{pct_low}">+{pct_low:.1f}%</td>
            <td class="text-right font-mono" data-order="{roc_3m}">{roc_3m:+.1f}%</td>
            <td class="text-right font-mono">{trading_val_str}</td>
            <td class="text-center" data-order="{vcp}">{vcp_badge} <small class="text-muted">({vcp:.2f})</small></td>
            {flow_cell}
        </tr>
        """
        rows_html.append(row)

    return "\n".join(rows_html)


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
            <td class="text-center font-mono">{r.get('buy_date', '-')}</td>
            <td class="text-right font-mono">{buy_str}</td>
            <td class="text-right font-mono font-bold">{curr_str}</td>
            <td class="text-right font-mono {ret_class}" data-order="{ret_pct}">{ret_pct:+.2f}%</td>
            <td class="text-right font-mono text-success" data-order="{max_ret}">+{max_ret:.1f}%</td>
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
    """한국 및 미국 주식 스크리닝과 보유종목 매도 감시를 통합한 3-탭 인터랙티브 HTML 대시보드를 생성합니다."""
    today_str = datetime.now().strftime("%Y년 %m월 %d일")

    kr_df = kr_df if kr_df is not None else pd.DataFrame()
    us_df = us_df if us_df is not None else pd.DataFrame()
    kr_new = kr_new or []
    us_new = us_new or []
    kr_drop = kr_drop or []
    us_drop = us_drop or []

    # 국내 주식 시가총액 5,000억원 이상 필터 (고승률 62.7% 챔피언 전략)
    if kr_df is not None and not kr_df.empty and "marcap" in kr_df.columns:
        kr_df = kr_df[pd.to_numeric(kr_df["marcap"], errors="coerce") >= 500_000_000_000].reset_index(drop=True)
    if kr_new:
        kr_new = [s for s in kr_new if s.get("marcap", 0) >= 500_000_000_000]
    if kr_drop:
        kr_drop = [s for s in kr_drop if s.get("marcap", 0) >= 500_000_000_000]

    # 포트폴리오 및 저장소 정보 로드
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

    # 매도 감시 데이터 로드
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

    # 시장 레짐 필터 데이터 로드
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

    kr_rows = build_tab_rows(kr_df, is_us=False)
    us_rows = build_tab_rows(us_df, is_us=True)
    sell_rows = build_sell_rows(sell_signals)

    kr_new_text = ", ".join([f"<strong>{s['name']}</strong>" for s in kr_new[:6]]) or "없음"
    kr_drop_text = ", ".join([f"{s['name']}" for s in kr_drop[:6]]) or "없음"
    us_new_text = ", ".join([f"<strong>{s['name']}</strong>({s['code']})" for s in us_new[:6]]) or "없음"
    us_drop_text = ", ".join([f"{s['name']}({s['code']})" for s in us_drop[:6]]) or "없음"

    sell_badge_bg = "#f85149" if urgent_sell_count > 0 else "#3fb950"

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>마크 미너비니 SEPA 통합 관제 대시보드 (매수 스크리너 & 매도 감시)</title>
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
            max-width: 1560px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #1f2937, #111827);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }}
        .header h1 {{
            margin: 0 0 8px 0;
            font-size: 26px;
            color: var(--text-heading);
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .header p {{
            margin: 4px 0;
            color: #8b949e;
            font-size: 14px;
            line-height: 1.5;
        }}
        /* Tab Navigation */
        .tab-nav {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .tab-btn {{
            background: #21262d;
            color: #8b949e;
            border: 1px solid var(--border-color);
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .tab-btn:hover {{
            color: #fff;
            border-color: var(--accent-blue);
        }}
        .tab-btn.active {{
            background: var(--accent-blue);
            color: #fff;
            border-color: var(--accent-blue);
            box-shadow: 0 0 12px rgba(88, 166, 255, 0.4);
        }}
        .tab-btn.tab-sell-btn.active {{
            background: linear-gradient(135deg, #da3633, #b62324);
            border-color: #f85149;
            box-shadow: 0 0 12px rgba(248, 81, 73, 0.4);
        }}
        .tab-badge {{
            background: rgba(0,0,0,0.25);
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        .change-banner {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            margin-top: 14px;
        }}
        .change-box {{
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 13px;
            line-height: 1.5;
        }}
        .change-new {{
            background: rgba(248, 81, 73, 0.1);
            border: 1px solid rgba(248, 81, 73, 0.4);
            color: #ff7b72;
        }}
        .change-drop {{
            background: rgba(139, 148, 158, 0.1);
            border: 1px solid rgba(139, 148, 158, 0.4);
            color: #8b949e;
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
        .sell-info-box {{
            background: rgba(248, 81, 73, 0.08);
            border: 1px solid rgba(248, 81, 73, 0.3);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 16px;
            font-size: 13px;
            color: #c9d1d9;
            line-height: 1.6;
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
        }}
        .stock-link:hover {{
            color: #79c0ff;
            text-decoration: underline;
        }}
        .finviz-link {{
            text-decoration: none;
            margin-left: 4px;
            opacity: 0.7;
        }}
        .finviz-link:hover {{ opacity: 1; }}
        .badge {{
            display: inline-block;
            padding: 4px 9px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 700;
        }}
        .badge-new {{
            background: linear-gradient(135deg, rgba(248, 81, 73, 0.3), rgba(241, 224, 90, 0.3));
            color: #ff7b72;
            border: 1px solid #f85149;
        }}
        .badge-days {{
            background-color: rgba(63, 185, 80, 0.15);
            color: #3fb950;
            border: 1px solid rgba(63, 185, 80, 0.4);
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
            border: 1px solid var(--border-color);
        }}
        .badge-super {{
            background-color: rgba(241, 224, 90, 0.25);
            color: #f1e05a;
            border: 1px solid #f1e05a;
        }}
        .badge-high {{
            background-color: rgba(63, 185, 80, 0.2);
            color: #3fb950;
        }}
        .badge-normal {{
            background-color: rgba(88, 166, 255, 0.15);
            color: #58a6ff;
        }}
        .badge-vcp-good {{
            background-color: rgba(63, 185, 80, 0.2);
            color: #3fb950;
            border: 1px solid rgba(63, 185, 80, 0.4);
        }}
        .badge-vcp-normal {{
            background-color: rgba(241, 224, 90, 0.15);
            color: #f1e05a;
        }}
        .badge-critical {{
            background: rgba(248, 81, 73, 0.25);
            color: #ff7b72;
            border: 1px solid #f85149;
        }}
        .badge-warning {{
            background: rgba(241, 224, 90, 0.2);
            color: #f1e05a;
            border: 1px solid #d29922;
        }}
        .badge-info {{
            background: rgba(88, 166, 255, 0.2);
            color: #58a6ff;
            border: 1px solid #388bfd;
        }}
        .badge-safe {{
            background: rgba(63, 185, 80, 0.2);
            color: #3fb950;
            border: 1px solid #2ea043;
        }}
        .market-tag {{
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .market-kospi {{ background: rgba(88, 166, 255, 0.2); color: #58a6ff; }}
        .market-kosdaq {{ background: rgba(241, 224, 90, 0.2); color: #f1e05a; }}
        .market-nasdaq {{ background: rgba(63, 185, 80, 0.2); color: #3fb950; }}
        .market-nyse {{ background: rgba(188, 140, 255, 0.2); color: #bc8cff; }}
        .market-kr {{ background: rgba(88, 166, 255, 0.2); color: #58a6ff; }}
        .market-us {{ background: rgba(63, 185, 80, 0.2); color: #3fb950; }}
        .text-success {{ color: var(--accent-green); }}
        .text-danger {{ color: var(--accent-red); }}
        .text-warning {{ color: var(--accent-gold); }}
        .text-muted {{ color: #8b949e; }}
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .font-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
        .font-bold {{ font-weight: 700; }}
        .sell-toolbar {{
            display: flex;
            gap: 10px;
            align-items: center;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            border: 1px solid var(--border-color);
            background: #21262d;
            color: var(--text-main);
            transition: all 0.2s ease;
        }}
        .btn:hover {{
            color: #fff;
            border-color: var(--accent-blue);
        }}
        .btn-green {{
            background: #238636;
            color: #fff;
            border-color: rgba(240,246,252,0.1);
        }}
        .btn-green:hover {{
            background: #2ea043;
        }}
        .btn-del {{
            background: transparent;
            border: 1px solid rgba(248, 81, 73, 0.4);
            color: #ff7b72;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn-del:hover {{
            background: rgba(248, 81, 73, 0.2);
            border-color: #f85149;
        }}
        /* Modals */
        .modal-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(3px);
            z-index: 10000;
            align-items: center;
            justify-content: center;
        }}
        .modal-box {{
            background: #161b22;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            width: 90%;
            max-width: 480px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.6);
            color: var(--text-main);
            box-sizing: border-box;
        }}
        .modal-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 12px;
        }}
        .modal-header h3 {{
            margin: 0;
            font-size: 18px;
            color: var(--text-heading);
        }}
        .modal-close {{
            background: none;
            border: none;
            color: #8b949e;
            font-size: 22px;
            cursor: pointer;
        }}
        .modal-close:hover {{
            color: #fff;
        }}
        .form-row {{
            display: flex;
            gap: 12px;
            margin-bottom: 12px;
        }}
        .form-field {{
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 6px;
            margin-bottom: 12px;
        }}
        .form-field label {{
            font-size: 12px;
            font-weight: 600;
            color: #8b949e;
        }}
        .form-input {{
            background: #0d1117;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            color: #c9d1d9;
            padding: 8px 12px;
            font-size: 14px;
            outline: none;
            width: 100%;
            box-sizing: border-box;
        }}
        .form-input:focus {{
            border-color: var(--accent-blue);
            box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.3);
        }}
        .toast-box {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            padding: 14px 20px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.6);
            z-index: 20000;
            display: none;
            color: #fff;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- 헤더 영역 -->
        <div class="header">
            <h1>🚀 마크 미너비니 SEPA 트렌드 템플릿 통합 대시보드</h1>
            <p>
                <strong>업데이트:</strong> {today_str} |
                <strong>국내 통과:</strong> <span class="text-success font-bold">{len(kr_df)}개</span> ({kr_regime_summary}) |
                <strong>미국 통과:</strong> <span class="text-success font-bold">{len(us_df)}개</span> ({us_regime_summary}) |
                <strong>보유 종목 감시:</strong> <span class="font-bold" style="color:{sell_badge_bg}">{len(sell_signals)}개 (경보 {urgent_sell_count}건)</span>
            </p>
            <div class="score-info-box">
                🎯 <strong>미너비니 원칙:</strong> 매수 타점 스크리너(1·2탭)로 최상위 모멘텀 종목을 잡고, 매도 감시 엔진(3탭)으로 <strong>-7~8% 손절 & 고점 10% 반락 시 이익보존 매도</strong>를 기계적으로 실행합니다.<br>
                🛡️ <strong>시장 필터:</strong> 지수 50일선 이탈(조정장) 시 <strong>신규 매수를 전면 중단하고 현금 100%를 보존</strong>하여 계좌 손실을 원천 방어합니다.
            </div>
        </div>

        <!-- 탭 네비게이션 버튼 -->
        <div class="tab-nav">
            <button class="tab-btn active" onclick="switchTab('kr')">
                🇰🇷 국내 주식 스크리너 (KOSPI / KOSDAQ)
                <span class="tab-badge">{len(kr_df)}개</span>
                {kr_tab_badge}
            </button>
            <button class="tab-btn" onclick="switchTab('us')">
                🇺🇸 미국 주식 스크리너 (NASDAQ / NYSE)
                <span class="tab-badge">{len(us_df)}개</span>
                {us_tab_badge}
            </button>
            <button class="tab-btn tab-sell-btn" onclick="switchTab('sell')">
                🛡️ 내 보유종목 매도 감시 (Sell Monitor)
                <span class="tab-badge" style="background:{sell_badge_bg}; color:#fff;">{len(sell_signals)}개</span>
            </button>
        </div>

        <!-- 탭 1: 한국 주식 -->
        <div id="tab-kr" class="tab-content active">
            {kr_regime_banner}
            {kr_block_warning}
            <div style="background:rgba(63,185,80,0.08); border:1px solid rgba(63,185,80,0.25); border-radius:8px; padding:12px 18px; margin-bottom:16px; font-size:13px; color:#c9d1d9; line-height:1.6;">
                🇰🇷 <strong>국내 주식 고승률(62.7%) & 고수익(+188%) 실전 매매 가이드:</strong><br>
                1. <strong>중대형 주도주 집중:</strong> 시가총액 5,000억원 이상 기관/외인 수급이 단단한 주도 업종(조선, 방산, 전력, 바이오 등) 집중 공략<br>
                2. <strong>추격 매수 엄격 금지 (Ext ≤ 1.08):</strong> 20일선에서 8% 이상 과열 급등한 종목은 매수하지 않고, <strong>20일선 눌림목 & VCP 변동성 수축(≤0.88)</strong> 타점에서만 진입<br>
                3. <strong>개별 시장 레짐 연동:</strong> 코스피 종목은 코스피 50일선 위, 코스닥 종목은 코스닥 50일선 위에서만 매수<br>
                4. <strong>3R 본전 보호:</strong> 손절폭(-7.5%)의 3배인 +22.5% 수익 달성 시 스탑을 매수가로 올려 원금을 영구 차단하고 큰 시세를 끝까지 향유<br>
                5. <strong>스마트머니 수급 참고(UI):</strong> 종목 우측 <strong>[메이저 수급]</strong> 컬럼에서 외인/기관 <strong>🔥 쌍끌이 매수</strong> 또는 <strong>🟢 기관 매수</strong> 동반 종목은 돌파 지지력이 우수하므로 매수 분할 진입 시 긍정적 보조 지표로 참고하세요. (반대로 메이저 기관 3일 이상 연속 매도 ⚠️ 종목은 추격 매수 자제)
            </div>
            <div class="change-banner" style="margin-bottom: 16px;">
                <div class="change-box change-new">
                    🔥 <strong>오늘 신규 편입 ({len(kr_new)}개):</strong> {kr_new_text}
                </div>
                <div class="change-box change-drop">
                    🚨 <strong>전일 대비 이탈 ({len(kr_drop)}개):</strong> {kr_drop_text}
                </div>
            </div>
            <div class="card">
                <table id="tableKR" class="display nowrap" style="width:100%">
                    <thead>
                        <tr>
                            <th class="text-center">순위</th>
                            <th>종목명 (코드)</th>
                            <th class="text-center">시장</th>
                            <th class="text-center">상태/연속</th>
                            <th class="text-center">SEPA점수</th>
                            <th class="text-right">시가총액</th>
                            <th class="text-right">현재가</th>
                            <th class="text-center">RS 상대강도</th>
                            <th class="text-right">52주고점거리</th>
                            <th class="text-right">52주저점상승</th>
                            <th class="text-right">3개월수익</th>
                            <th class="text-right">20일거래대금</th>
                            <th class="text-center">VCP변동성</th>
                            <th class="text-center">메이저 수급 (5일)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {kr_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 탭 2: 미국 주식 -->
        <div id="tab-us" class="tab-content">
            {us_regime_banner}
            {us_block_warning}
            <div style="background:rgba(88,166,255,0.08); border:1px solid rgba(88,166,255,0.25); border-radius:8px; padding:12px 18px; margin-bottom:16px; font-size:13px; color:#c9d1d9; line-height:1.6;">
                🇺🇸 <strong>미국 주식 고승률(48%) 실전 매매 가이드:</strong><br>
                1. <strong>대형 우량주 집중:</strong> 기관 수급이 보장된 S&P 500 / NASDAQ 대형주 위주 공략 (초소형 페니주 휩소 배제)<br>
                2. <strong>추격 매수 금지 (Ext ≤ 1.06):</strong> 20일선에서 6% 이상 과열된 종목은 매수하지 않고, <strong>변동성 수축(VCP ≤ 0.90) 구간</strong>에서만 진입<br>
                3. <strong>어닝 룰렛 회피:</strong> 분기 실적 발표 전 수익 쿠션(+10% 이상)이 없으면 비중을 절반 이상 축소하여 밤사이 갭하락 위험 차단<br>
                4. <strong>3R 본전 보호:</strong> 손절폭(-7.5%)의 3배인 +22.5% 수익 달성 시 스탑을 매수가로 상향하여 원금 영구 보호
            </div>
            <div class="change-banner" style="margin-bottom: 16px;">
                <div class="change-box change-new">
                    🔥 <strong>오늘 신규 편입 ({len(us_new)}개):</strong> {us_new_text}
                </div>
                <div class="change-box change-drop">
                    🚨 <strong>전일 대비 이탈 ({len(us_drop)}개):</strong> {us_drop_text}
                </div>
            </div>
            <div class="card">
                <table id="tableUS" class="display nowrap" style="width:100%">
                    <thead>
                        <tr>
                            <th class="text-center">순위</th>
                            <th>티커 (기업명)</th>
                            <th class="text-center">거래소</th>
                            <th class="text-center">상태/연속</th>
                            <th class="text-center">SEPA점수</th>
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
                        {us_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 탭 3: 보유 종목 매도 감시 -->
        <div id="tab-sell" class="tab-content">
            <div class="sell-info-box">
                🛡️ <strong>마크 미너비니 핵심 매도 원칙 가이드:</strong><br>
                1. <strong>손실 통제 (1R Cut):</strong> 매수가 대비 -7~8% 하락 시 어떤 이유도 묻지 않고 <strong>기계적 전량 손절</strong>합니다.<br>
                2. <strong>본전 보호 (3R Break-Even):</strong> 손절폭(-7.5%)의 3배인 <strong>+22.5% 이상 상승했던 종목은 스탑을 매수가로 상향</strong>하여 원금 손실 위험을 0%로 영구 차단합니다 (정상적인 8~10% 눌림목에서의 조기 탈락 방지).<br>
                3. <strong>이익 보존:</strong> +20% 이상 큰 시세가 난 종목은 <strong>고점 대비 -10% 반락 시 트레일링 익절</strong>하여 수익을 확정 짓습니다.<br>
                4. <strong>실적 발표 갭다운 회피:</strong> 실적 발표 전 수익 쿠션(+10% 이상)이 없는 종목은 위험 축소 또는 단기 급락 시 조기 차단합니다.<br>
                5. <strong>클라이맥스:</strong> 200일선 70%+ 수직 급등 시 <strong>강세 구간에서 보유 물량의 1/2을 분할 매도</strong>합니다.<br>
                <small class="text-muted">👉 보유 종목 관리: 아래 <strong>[➕ 새 보유 종목 추가]</strong> / 테이블 우측 <strong>[🗑️ 삭제]</strong> 버튼으로 웹에서 바로 관리할 수 있습니다.</small>
            </div>

            <div class="sell-toolbar">
                <button class="btn btn-green font-bold" onclick="openAddModal()">
                    ➕ 새 보유 종목 추가
                </button>
                <button class="btn" onclick="openGhSyncModal()">
                    ⚙️ GitHub 클라우드 직접 연동 <span id="ghSyncBadge" class="badge" style="font-size:11px; margin-left:4px;">확인 중...</span>
                </button>
                <a href="http://localhost:5050" target="_blank" class="btn" style="text-decoration:none;">
                    💻 PC 로컬 웹 관리자 열기
                </a>
                <button class="btn" onclick="exportPortfolioJson()">
                    📥 portfolio.json 다운로드
                </button>
            </div>

            <div class="card">
                <table id="tableSell" class="display nowrap" style="width:100%">
                    <thead>
                        <tr>
                            <th class="text-center">순번</th>
                            <th>보유 종목 (코드)</th>
                            <th class="text-center">시장</th>
                            <th class="text-center">매수일자</th>
                            <th class="text-right">매수가</th>
                            <th class="text-right">현재가</th>
                            <th class="text-right">현재 손익</th>
                            <th class="text-right">최고 수익</th>
                            <th class="text-right">고점거리</th>
                            <th class="text-center">미너비니 매도진단</th>
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
    </div>

    <!-- 종목 추가 모달 -->
    <div id="modalAddStock" class="modal-overlay">
        <div class="modal-box">
            <div class="modal-header">
                <h3>➕ 새 보유 종목 추가</h3>
                <button class="modal-close" onclick="closeModal('modalAddStock')">&times;</button>
            </div>
            <div>
                <div class="form-row">
                    <div class="form-field">
                        <label>시장 구분</label>
                        <select id="webMarket" class="form-input">
                            <option value="KR">🇰🇷 국내 주식 (KR)</option>
                            <option value="US">🇺🇸 미국 주식 (US)</option>
                        </select>
                    </div>
                    <div class="form-field">
                        <label>종목코드 / 티커</label>
                        <input type="text" id="webCode" class="form-input" placeholder="예: 000500, AAPL">
                    </div>
                </div>
                <div class="form-field">
                    <label>종목명</label>
                    <input type="text" id="webName" class="form-input" placeholder="예: 가온전선, Apple Inc.">
                </div>
                <div class="form-row">
                    <div class="form-field">
                        <label>매수가격 (단가)</label>
                        <input type="number" id="webPrice" class="form-input" placeholder="예: 318000 또는 150.5" step="any">
                    </div>
                    <div class="form-field">
                        <label>매수일자</label>
                        <input type="date" id="webDate" class="form-input">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-field">
                        <label>보유수량 (주)</label>
                        <input type="number" id="webShares" class="form-input" value="1" min="1">
                    </div>
                    <div class="form-field">
                        <label>메모 (선택)</label>
                        <input type="text" id="webMemo" class="form-input" placeholder="예: SEPA VCP 돌파">
                    </div>
                </div>
                <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
                    <button class="btn" onclick="closeModal('modalAddStock')">취소</button>
                    <button class="btn btn-green" onclick="submitWebAddStock()">💾 저장하기</button>
                </div>
            </div>
        </div>
    </div>

    <!-- GitHub 클라우드 연동 모달 -->
    <div id="modalGhSync" class="modal-overlay">
        <div class="modal-box">
            <div class="modal-header">
                <h3>⚙️ GitHub 클라우드 직접 연동 설정</h3>
                <button class="modal-close" onclick="closeModal('modalGhSync')">&times;</button>
            </div>
            <div>
                <p style="font-size:13px; line-height:1.6; color:#8b949e; margin-top:0;">
                    스마트폰이나 다른 브라우저에서 종목을 추가/삭제하면 별도의 PC 프로그램 실행 없이 GitHub 저장소의 <code>portfolio.json</code>을 즉시 원격 업데이트합니다.<br>
                    <small style="color:var(--accent-gold);">🔒 토큰은 외부 서버로 전송되지 않으며, 현재 사용 중인 브라우저의 로컬 스토리지에만 안전하게 저장됩니다.</small>
                </p>
                <div class="form-field">
                    <label>GitHub 저장소 (기본값)</label>
                    <input type="text" id="ghRepoInput" class="form-input" value="{repo_name}">
                </div>
                <div class="form-field">
                    <label>GitHub Personal Access Token (PAT)</label>
                    <input type="password" id="ghTokenInput" class="form-input" placeholder="ghp_...">
                </div>
                <div id="ghStatusText" style="font-size:13px; margin: 10px 0 16px 0;"></div>
                <div style="display:flex; justify-content:space-between; gap:8px;">
                    <button class="btn" style="color:#ff7b72; border-color:rgba(248,81,73,0.4);" onclick="clearGhToken()">연동 해제</button>
                    <div style="display:flex; gap:8px;">
                        <button class="btn" onclick="closeModal('modalGhSync')">닫기</button>
                        <button class="btn btn-green" onclick="saveGhToken()">토큰 저장 및 검증</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- 토스트 알림창 -->
    <div id="webToast" class="toast-box"></div>

    <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
    <script>
        let currentPortfolio = {portfolio_json_str};
        const DEFAULT_REPO = "{repo_name}";

        function showWebToast(msg, isError = false) {{
            const t = document.getElementById('webToast');
            t.innerText = msg;
            t.style.background = isError ? '#da3633' : '#238636';
            t.style.display = 'block';
            setTimeout(() => {{ t.style.display = 'none'; }}, 3500);
        }}

        function openModal(id) {{
            const el = document.getElementById(id);
            if (el) el.style.display = 'flex';
        }}

        function closeModal(id) {{
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        }}

        function openAddModal() {{
            document.getElementById('webDate').value = new Date().toISOString().split('T')[0];
            openModal('modalAddStock');
        }}

        function openGhSyncModal(warnNotice = false) {{
            const savedToken = localStorage.getItem('minervini_gh_token') || '';
            const savedRepo = localStorage.getItem('minervini_gh_repo') || DEFAULT_REPO;
            document.getElementById('ghTokenInput').value = savedToken;
            document.getElementById('ghRepoInput').value = savedRepo;

            const statusEl = document.getElementById('ghStatusText');
            if (savedToken) {{
                statusEl.innerHTML = '<span class="text-success font-bold">🟢 GitHub 클라우드 연동 완료</span> (웹에서 추가/삭제 시 자동 반영)';
            }} else {{
                statusEl.innerHTML = warnNotice 
                    ? '<span class="text-warning font-bold">⚠️ GitHub 토큰을 등록하시면 웹에서 추가/삭제한 내역이 GitHub 저장소에 영구 동기화됩니다.</span>'
                    : '<span class="text-muted">⚪ 아직 토큰이 등록되지 않았습니다.</span>';
            }}
            openModal('modalGhSync');
        }}

        async function saveGhToken() {{
            const token = document.getElementById('ghTokenInput').value.trim();
            const repo = document.getElementById('ghRepoInput').value.trim() || DEFAULT_REPO;
            if (!token) {{
                alert('GitHub 토큰(PAT)을 입력해주세요.');
                return;
            }}

            showWebToast('⏳ 토큰 유효성 검증 중...');
            try {{
                const res = await fetch(`https://api.github.com/repos/${{repo}}`, {{
                    headers: {{ 'Authorization': `token ${{token}}`, 'Accept': 'application/vnd.github.v3+json' }}
                }});
                if (res.ok) {{
                    localStorage.setItem('minervini_gh_token', token);
                    localStorage.setItem('minervini_gh_repo', repo);
                    updateGhSyncBadge();
                    showWebToast('🎉 GitHub 클라우드 연동 성공!');
                    closeModal('modalGhSync');
                }} else {{
                    showWebToast('❌ 토큰 또는 저장소 권한 확인 실패', true);
                }}
            }} catch (e) {{
                showWebToast('❌ 네트워크 오류: ' + e.message, true);
            }}
        }}

        function clearGhToken() {{
            if (!confirm('저장된 GitHub 토큰을 삭제하시겠습니까?')) return;
            localStorage.removeItem('minervini_gh_token');
            updateGhSyncBadge();
            showWebToast('토큰이 삭제되었습니다.');
            closeModal('modalGhSync');
        }}

        function updateGhSyncBadge() {{
            const badge = document.getElementById('ghSyncBadge');
            if (!badge) return;
            const token = localStorage.getItem('minervini_gh_token');
            if (token) {{
                badge.innerHTML = '🟢 연동됨';
                badge.className = 'badge badge-safe';
            }} else {{
                badge.innerHTML = '⚪ 미연동';
                badge.className = 'badge badge-silver';
            }}
        }}

        async function syncToGitHubApi(newPortfolio, commitMsg) {{
            const token = localStorage.getItem('minervini_gh_token');
            const repo = localStorage.getItem('minervini_gh_repo') || DEFAULT_REPO;
            if (!token) {{
                openGhSyncModal(true);
                return false;
            }}

            try {{
                showWebToast('⏳ GitHub 저장소에 동기화 중...');
                const getUrl = `https://api.github.com/repos/${{repo}}/contents/portfolio.json`;
                const getRes = await fetch(getUrl, {{
                    headers: {{ 'Authorization': `token ${{token}}`, 'Accept': 'application/vnd.github.v3+json' }}
                }});

                let sha = null;
                if (getRes.ok) {{
                    const data = await getRes.json();
                    sha = data.sha;
                }}

                const jsonStr = JSON.stringify(newPortfolio, null, 2);
                const utf8Bytes = new TextEncoder().encode(jsonStr);
                let binaryStr = '';
                utf8Bytes.forEach(b => binaryStr += String.fromCharCode(b));
                const base64Content = btoa(binaryStr);

                const putRes = await fetch(getUrl, {{
                    method: 'PUT',
                    headers: {{
                        'Authorization': `token ${{token}}`,
                        'Content-Type': 'application/json',
                        'Accept': 'application/vnd.github.v3+json'
                    }},
                    body: JSON.stringify({{
                        message: commitMsg,
                        content: base64Content,
                        sha: sha || undefined
                    }})
                }});

                if (putRes.ok) {{
                    showWebToast('🎉 GitHub 저장소에 성공적으로 동기화되었습니다!');
                    return true;
                }} else {{
                    const err = await putRes.json();
                    showWebToast('❌ 동기화 실패: ' + (err.message || '권한 오류'), true);
                    return false;
                }}
            }} catch (e) {{
                showWebToast('❌ 통신 오류: ' + e.message, true);
                return false;
            }}
        }}

        async function submitWebAddStock() {{
            const market = document.getElementById('webMarket').value;
            const code = document.getElementById('webCode').value.trim().toUpperCase();
            const name = document.getElementById('webName').value.trim() || code;
            const price = parseFloat(document.getElementById('webPrice').value);
            const date = document.getElementById('webDate').value;
            const shares = parseInt(document.getElementById('webShares').value) || 1;
            const memo = document.getElementById('webMemo').value.trim();

            if (!code || isNaN(price) || price <= 0) {{
                alert('종목코드와 올바른 매수가격을 입력해주세요.');
                return;
            }}

            const item = {{ code, name, market, buy_price: price, buy_date: date, shares, memo }};
            const idx = currentPortfolio.findIndex(p => String(p.code).toUpperCase() === code);
            if (idx >= 0) {{
                currentPortfolio[idx] = item;
            }} else {{
                currentPortfolio.push(item);
            }}

            closeModal('modalAddStock');

            const synced = await syncToGitHubApi(currentPortfolio, `Add/Update stock ${{code}} (${{name}}) via web`);
            if (!synced) {{
                showWebToast(`[${{code}}] 로컬 반영 완료! (GitHub 클라우드에 영구 저장하려면 상단 연동 설정을 완료하세요)`);
            }}

            setTimeout(() => {{ location.reload(); }}, 1500);
        }}

        async function deleteStockFromWeb(code, name) {{
            if (!confirm(`정말 [${{name || code}}] 종목을 포트폴리오에서 삭제하시겠습니까?`)) return;

            currentPortfolio = currentPortfolio.filter(p => String(p.code).toUpperCase() !== String(code).toUpperCase());

            const row = document.getElementById(`sell-row-${{code}}`);
            if (row) {{
                row.style.opacity = '0.3';
                row.style.background = 'rgba(248, 81, 73, 0.2)';
            }}

            const synced = await syncToGitHubApi(currentPortfolio, `Delete stock ${{code}} (${{name}}) via web`);
            if (!synced) {{
                showWebToast(`[${{code}}] 삭제 완료! (클라우드 반영은 연동 필요)`);
            }}

            setTimeout(() => {{ location.reload(); }}, 1500);
        }}

        function exportPortfolioJson() {{
            const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentPortfolio, null, 2));
            const dlAnchor = document.createElement('a');
            dlAnchor.setAttribute("href", dataStr);
            dlAnchor.setAttribute("download", "portfolio.json");
            document.body.appendChild(dlAnchor);
            dlAnchor.click();
            dlAnchor.remove();
            showWebToast('📥 portfolio.json 다운로드 완료!');
        }}

        $(document).ready(function() {{
            updateGhSyncBadge();

            const tableKR = $('#tableKR').DataTable({{
                pageLength: 25,
                order: [[4, 'desc']],
                language: {{
                    search: "국내 종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: {{ first: "처음", last: "마지막", next: "다음", previous: "이전" }}
                }}
            }});

            const tableUS = $('#tableUS').DataTable({{
                pageLength: 25,
                order: [[4, 'desc']],
                language: {{
                    search: "미국 티커/종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: {{ first: "처음", last: "마지막", next: "다음", previous: "이전" }}
                }}
            }});

            const tableSell = $('#tableSell').DataTable({{
                pageLength: 25,
                order: [[6, 'desc']], // 현재 수익률 기준 정렬
                columnDefs: [{{ orderable: false, targets: [12] }}],
                language: {{
                    search: "보유 종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: {{ first: "처음", last: "마지막", next: "다음", previous: "이전" }}
                }}
            }});

            window.switchTab = function(tab) {{
                $('.tab-btn').removeClass('active');
                $('.tab-content').removeClass('active');

                if (tab === 'kr') {{
                    $('.tab-btn').eq(0).addClass('active');
                    $('#tab-kr').addClass('active');
                    tableKR.columns.adjust().draw();
                }} else if (tab === 'us') {{
                    $('.tab-btn').eq(1).addClass('active');
                    $('#tab-us').addClass('active');
                    tableUS.columns.adjust().draw();
                }} else if (tab === 'sell') {{
                    $('.tab-btn').eq(2).addClass('active');
                    $('#tab-sell').addClass('active');
                    tableSell.columns.adjust().draw();
                }}
            }};
        }});
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

    print(f"[*] 한/미 스크리너 및 매도 감시 통합 대시보드 생성 완료: {output_path}")
    return output_path
