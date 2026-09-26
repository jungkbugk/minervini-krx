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
    if df.empty:
        return '<tr><td colspan="13" class="text-center py-4">조건을 통과한 종목이 없습니다.</td></tr>'

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
        </tr>
        """
        rows_html.append(row)

    return "\n".join(rows_html)


def build_sell_rows(sell_signals: list[dict]) -> str:
    """내 보유 종목 매도 감시 테이블 행 HTML을 생성합니다."""
    if not sell_signals:
        return '<tr><td colspan="12" class="text-center py-4">등록된 보유 종목이 없습니다. 터미널에서 <code>python portfolio_manager.py</code> 명령어로 보유 종목을 등록하세요.</td></tr>'

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
        <tr>
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
    </style>
</head>
<body>
    <div class="container">
        <!-- 헤더 영역 -->
        <div class="header">
            <h1>🚀 마크 미너비니 SEPA 트렌드 템플릿 통합 대시보드</h1>
            <p>
                <strong>업데이트:</strong> {today_str} |
                <strong>국내 통과:</strong> <span class="text-success font-bold">{len(kr_df)}개</span> |
                <strong>미국 통과:</strong> <span class="text-success font-bold">{len(us_df)}개</span> |
                <strong>보유 종목 감시:</strong> <span class="font-bold" style="color:{sell_badge_bg}">{len(sell_signals)}개 (경보 {urgent_sell_count}건)</span>
            </p>
            <div class="score-info-box">
                🎯 <strong>미너비니 원칙:</strong> 매수 타점 스크리너(1·2탭)로 최상위 모멘텀 종목을 잡고, 매도 감시 엔진(3탭)으로 <strong>-7~8% 손절 & 고점 10% 반락 시 이익보존 매도</strong>를 기계적으로 실행합니다.
            </div>
        </div>

        <!-- 탭 네비게이션 버튼 -->
        <div class="tab-nav">
            <button class="tab-btn active" onclick="switchTab('kr')">
                🇰🇷 국내 주식 스크리너 (KOSPI / KOSDAQ)
                <span class="tab-badge">{len(kr_df)}개</span>
            </button>
            <button class="tab-btn" onclick="switchTab('us')">
                🇺🇸 미국 주식 스크리너 (NASDAQ / NYSE)
                <span class="tab-badge">{len(us_df)}개</span>
            </button>
            <button class="tab-btn tab-sell-btn" onclick="switchTab('sell')">
                🛡️ 내 보유종목 매도 감시 (Sell Monitor)
                <span class="tab-badge" style="background:{sell_badge_bg}; color:#fff;">{len(sell_signals)}개</span>
            </button>
        </div>

        <!-- 탭 1: 한국 주식 -->
        <div id="tab-kr" class="tab-content active">
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
                1. <strong>손실 통제:</strong> 매수가 대비 -7~8% 하락 시 어떤 이유도 묻지 않고 <strong>기계적 전량 손절</strong>합니다.<br>
                2. <strong>본전 보호:</strong> +12% 이상 상승했던 종목은 스탑을 매수가로 올려 <strong>원금 손실 위험을 0%</strong>로 만듭니다.<br>
                3. <strong>이익 보존:</strong> +20% 이상 큰 시세가 난 종목은 <strong>고점 대비 -10% 반락 시 트레일링 익절</strong>하여 수익을 확정 짓습니다.<br>
                4. <strong>클라이맥스:</strong> 200일선 70%+ 수직 급등 시 <strong>강세 구간에서 보유 물량의 1/2을 분할 매도</strong>합니다.<br>
                <small class="text-muted">👉 보유 종목 추가/수정/삭제: 터미널에서 <code>python portfolio_manager.py</code> 명령어를 실행하세요.</small>
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
                        </tr>
                    </thead>
                    <tbody>
                        {sell_rows}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
    <script>
        $(document).ready(function() {{
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

    print(f"[*] 한/미 스크리너 및 매도 감시 통합 대시보드 생성 완료: {output_path}")
    return output_path
