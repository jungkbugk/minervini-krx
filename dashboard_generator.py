"""국내 주식(KR)과 미국 주식(US)을 하나의 웹 대시보드에서 탭으로 전환하여 조회하는 통합 HTML 대시보드 생성기"""

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
    """각 시장별 테이블 행 HTML을 생성합니다."""
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

        # 차트 링크 (한국: 네이버 증권, 미국: 트레이딩뷰)
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

        # 뱃지 구성
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


def generate_unified_dashboard(
    kr_df: pd.DataFrame | None = None,
    us_df: pd.DataFrame | None = None,
    kr_new: list[dict] | None = None,
    us_new: list[dict] | None = None,
    kr_drop: list[dict] | None = None,
    us_drop: list[dict] | None = None,
    output_path: str = "index.html",
) -> str:
    """한국 및 미국 주식 데이터를 통합한 탭 전환 인터랙티브 HTML 대시보드를 생성합니다."""
    today_str = datetime.now().strftime("%Y년 %m월 %d일")

    kr_df = kr_df if kr_df is not None else pd.DataFrame()
    us_df = us_df if us_df is not None else pd.DataFrame()
    kr_new = kr_new or []
    us_new = us_new or []
    kr_drop = kr_drop or []
    us_drop = us_drop or []

    kr_rows = build_tab_rows(kr_df, is_us=False)
    us_rows = build_tab_rows(us_df, is_us=True)

    kr_new_text = ", ".join([f"<strong>{s['name']}</strong>" for s in kr_new[:6]]) or "없음"
    kr_drop_text = ", ".join([f"{s['name']}" for s in kr_drop[:6]]) or "없음"
    us_new_text = ", ".join([f"<strong>{s['name']}</strong>({s['code']})" for s in us_new[:6]]) or "없음"
    us_drop_text = ", ".join([f"{s['name']}({s['code']})" for s in us_drop[:6]]) or "없음"

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>마크 미너비니 SEPA 글로벌 주식 스크리너 (한/미 통합)</title>
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
            border: 1px solid rgba(139, 148, 158, 0.5);
        }}
        .badge-super {{ background-color: rgba(241, 224, 90, 0.15); color: #f1e05a; }}
        .badge-high {{ background-color: rgba(63, 185, 80, 0.15); color: #3fb950; }}
        .badge-normal {{ background-color: rgba(88, 166, 255, 0.15); color: #58a6ff; }}
        .badge-vcp-good {{
            background-color: rgba(63, 185, 80, 0.15);
            color: #3fb950;
            border: 1px solid rgba(63, 185, 80, 0.3);
        }}
        .badge-vcp-normal {{ background-color: rgba(210, 153, 34, 0.15); color: #d29922; }}
        .badge-muted {{ background-color: rgba(139, 148, 158, 0.15); color: #8b949e; }}
        .market-tag {{
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 500;
        }}
        .market-kospi {{ background: #233446; color: #79c0ff; }}
        .market-kosdaq {{ background: #3d2a45; color: #d2a8ff; }}
        .market-kosdaqglobal {{ background: #3c3222; color: #e3b341; }}
        .market-nasdaq {{ background: #1e3a5f; color: #38bdf8; }}
        .market-nyse {{ background: #3b204e; color: #c084fc; }}
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .text-danger {{ color: var(--accent-red); }}
        .text-warning {{ color: #e3b341; }}
        .text-success {{ color: var(--accent-green); }}
        .text-muted {{ color: #8b949e; }}
        .font-bold {{ font-weight: 600; }}
        .font-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
        .dataTables_wrapper .dataTables_length,
        .dataTables_wrapper .dataTables_filter,
        .dataTables_wrapper .dataTables_info,
        .dataTables_wrapper .dataTables_paginate {{
            color: #8b949e !important;
            font-size: 13px;
            margin-bottom: 12px;
        }}
        .dataTables_wrapper .dataTables_filter input {{
            background: #21262d;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            color: #fff;
            padding: 6px 10px;
            margin-left: 8px;
        }}
        .dataTables_wrapper .dataTables_paginate .paginate_button {{
            color: #8b949e !important;
            border-radius: 4px !important;
        }}
        .dataTables_wrapper .dataTables_paginate .paginate_button.current {{
            background: #21262d !important;
            border-color: var(--border-color) !important;
            color: #fff !important;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌐 마크 미너비니 SEPA 글로벌 트렌드 템플릿 대시보드</h1>
            <p>
                <strong>산출 기준일:</strong> {today_str} |
                <strong>국내 종목:</strong> <span class="text-success font-bold">{len(kr_df)}개</span> |
                <strong>미국 종목:</strong> <span class="text-success font-bold">{len(us_df)}개</span> |
                <strong>정렬:</strong> SEPA 종합 점수 (100점 만점) 내림차순
            </p>
            <div class="score-info-box">
                🎯 <strong>SEPA 종합 점수(100점 만점) 가중치:</strong>
                상대강도 모멘텀(35점) + 신고가 돌파 근접도(25점) + VCP 변동성 축소 패턴(20점) + 200일선 정배열 가속도(10점) + 거래대금 유동성(10점)
            </div>
        </div>

        <!-- 탭 네비게이션 버튼 -->
        <div class="tab-nav">
            <button class="tab-btn active" onclick="switchTab('kr')">
                🇰🇷 국내 주식 (KOSPI / KOSDAQ)
                <span class="tab-badge">{len(kr_df)}개</span>
            </button>
            <button class="tab-btn" onclick="switchTab('us')">
                🇺🇸 미국 주식 (NASDAQ / NYSE)
                <span class="tab-badge">{len(us_df)}개</span>
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
    </div>

    <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
    <script>
        $(document).ready(function() {{
            const tableKR = $('#tableKR').DataTable({{
                pageLength: 25,
                order: [[4, 'desc']], // SEPA 점수 기준 정렬
                language: {{
                    search: "국내 종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: {{ first: "처음", last: "마지막", next: "다음", previous: "이전" }}
                }}
            }});

            const tableUS = $('#tableUS').DataTable({{
                pageLength: 25,
                order: [[4, 'desc']], // SEPA 점수 기준 정렬
                language: {{
                    search: "미국 티커/종목 검색:",
                    lengthMenu: "_MENU_ 개씩 보기",
                    info: "총 _TOTAL_개 중 _START_ ~ _END_ 표시",
                    paginate: {{ first: "처음", last: "마지막", next: "다음", previous: "이전" }}
                }}
            }});

            window.switchTab = function(tab) {{
                $('.tab-btn').removeClass('active');
                $('.tab-content').removeClass('active');

                if (tab === 'kr') {{
                    $('.tab-btn:first').addClass('active');
                    $('#tab-kr').addClass('active');
                    tableKR.columns.adjust().draw();
                }} else {{
                    $('.tab-btn:last').addClass('active');
                    $('#tab-us').addClass('active');
                    tableUS.columns.adjust().draw();
                }}
            }};
        }});
    </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"🌐 한/미 통합 대시보드 생성 완료: {output_path}")
    return output_path
