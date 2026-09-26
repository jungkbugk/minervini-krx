"""마크 미너비니 포트폴리오 웹 관리자 (로컬 웹 대시보드 및 종목 추가/삭제/분석)"""

from __future__ import annotations

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import subprocess
import sys
import urllib.parse
import webbrowser

import FinanceDataReader as fdr
import pandas as pd

# Windows 콘솔 UTF-8 설정
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PORT = 5050
PORTFOLIO_FILE = "portfolio.json"
SIGNALS_FILE = os.path.join("history", "latest_sell_signals.json")


def get_portfolio() -> list[dict]:
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_portfolio(positions: list[dict]) -> None:
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def get_sell_signals() -> list[dict]:
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


HTML_PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>마크 미너비니 포트폴리오 웹 관리자</title>
    <style>
        :root {
            --bg-color: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --text-heading: #f0f6fc;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-gold: #f1e05a;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 24px;
        }
        .container {
            max-width: 1300px;
            margin: 0 auto;
        }
        .header {
            background: linear-gradient(135deg, #1f2937, #111827);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            margin: 0 0 6px 0;
            font-size: 24px;
            color: var(--text-heading);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .header p {
            margin: 0;
            color: #8b949e;
            font-size: 14px;
        }
        .btn {
            background: #238636;
            color: #fff;
            border: 1px solid rgba(240,246,252,0.1);
            padding: 10px 18px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .btn:hover { background: #2ea043; }
        .btn-blue { background: #1f6feb; }
        .btn-blue:hover { background: #388bfd; }
        .btn-danger { background: #da3633; padding: 6px 12px; font-size: 12px; }
        .btn-danger:hover { background: #f85149; }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }
        .card h2 {
            margin: 0 0 16px 0;
            font-size: 18px;
            color: var(--text-heading);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 14px;
            margin-bottom: 16px;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .form-group label {
            font-size: 12px;
            font-weight: 600;
            color: #8b949e;
        }
        .form-control {
            background: #0d1117;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            color: #c9d1d9;
            padding: 8px 12px;
            font-size: 14px;
            outline: none;
        }
        .form-control:focus {
            border-color: var(--accent-blue);
            box-shadow: 0 0 0 2px rgba(88,166,255,0.3);
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        th {
            background: #21262d;
            color: #f0f6fc;
            padding: 12px 10px;
            text-align: left;
            border-bottom: 2px solid var(--border-color);
        }
        td {
            padding: 12px 10px;
            border-bottom: 1px solid #21262d;
        }
        tr:hover {
            background: rgba(56, 139, 253, 0.05);
        }
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 700;
        }
        .badge-critical { background: rgba(248,81,73,0.25); color: #ff7b72; border: 1px solid #f85149; }
        .badge-warning { background: rgba(241,224,90,0.2); color: #f1e05a; border: 1px solid #d29922; }
        .badge-safe { background: rgba(63,185,80,0.2); color: #3fb950; border: 1px solid #2ea043; }
        .tag-kr { background: rgba(88,166,255,0.2); color: #58a6ff; font-weight: bold; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
        .tag-us { background: rgba(63,185,80,0.2); color: #3fb950; font-weight: bold; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
        .text-success { color: var(--accent-green); font-weight: bold; }
        .text-danger { color: var(--accent-red); font-weight: bold; }
        .text-warning { color: var(--accent-gold); font-weight: bold; }
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #238636;
            color: #fff;
            padding: 14px 20px;
            border-radius: 8px;
            display: none;
            box-shadow: 0 4px 16px rgba(0,0,0,0.5);
            font-weight: 600;
            z-index: 1000;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- 헤더 -->
        <div class="header">
            <div>
                <h1>💼 마크 미너비니 포트폴리오 웹 관리자</h1>
                <p>보유 종목을 실시간으로 추가/삭제하고, 미너비니 6대 매도 원칙을 감시합니다.</p>
            </div>
            <div style="display:flex; gap:10px;">
                <button class="btn btn-blue" onclick="runSellAnalysis()">
                    🚀 매도 진단 & GitHub 즉시 동기화
                </button>
                <a href="https://jungkbugk.github.io/minervini-krx/" target="_blank" class="btn" style="text-decoration:none;">
                    🌐 내 공개 대시보드 가기
                </a>
            </div>
        </div>

        <!-- 1. 종목 등록 카드 -->
        <div class="card">
            <h2>➕ 새 보유 종목 추가하기</h2>
            <div class="form-grid">
                <div class="form-group">
                    <label>시장 구분</label>
                    <select id="inputMarket" class="form-control" onchange="autoLookupPrice()">
                        <option value="KR">🇰🇷 국내 주식 (KR)</option>
                        <option value="US">🇺🇸 미국 주식 (US)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>종목코드 / 티커</label>
                    <input type="text" id="inputCode" class="form-control" placeholder="예: 000500, AAPL" onblur="autoLookupPrice()">
                </div>
                <div class="form-group">
                    <label>종목명 (자동입력)</label>
                    <input type="text" id="inputName" class="form-control" placeholder="조회 시 자동 완성">
                </div>
                <div class="form-group">
                    <label>매수가격 (단가)</label>
                    <input type="number" id="inputPrice" class="form-control" placeholder="예: 318000 또는 150.5" step="any">
                </div>
                <div class="form-group">
                    <label>매수일자</label>
                    <input type="date" id="inputDate" class="form-control">
                </div>
                <div class="form-group">
                    <label>수량 (선택)</label>
                    <input type="number" id="inputShares" class="form-control" value="1" min="1">
                </div>
                <div class="form-group">
                    <label>메모 (선택)</label>
                    <input type="text" id="inputMemo" class="form-control" placeholder="예: SEPA VCP 돌파">
                </div>
            </div>
            <button class="btn" onclick="submitAddStock()">
                💾 포트폴리오에 종목 추가
            </button>
        </div>

        <!-- 2. 보유 종목 및 매도 진단 현황 카드 -->
        <div class="card">
            <h2>🛡️ 현재 보유 종목 및 미너비니 매도 진단 현황</h2>
            <div style="overflow-x:auto;">
                <table id="portfolioTable">
                    <thead>
                        <tr>
                            <th style="width:40px; text-align:center;">#</th>
                            <th>시장</th>
                            <th>종목명 (코드)</th>
                            <th>매수일자</th>
                            <th style="text-align:right;">매수가</th>
                            <th style="text-align:right;">현재가</th>
                            <th style="text-align:right;">현재수익</th>
                            <th style="text-align:right;">최고수익</th>
                            <th>미너비니 매도진단</th>
                            <th style="text-align:right;">권장스탑선</th>
                            <th>대응 가이드</th>
                            <th style="width:60px; text-align:center;">관리</th>
                        </tr>
                    </thead>
                    <tbody id="tableBody">
                        <tr><td colspan="12" style="text-align:center; padding:20px;">로딩 중...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div id="toast" class="toast">저장되었습니다!</div>

    <script>
        // 오늘 날짜 기본 설정
        document.getElementById('inputDate').value = new Date().toISOString().split('T')[0];

        function showToast(msg, isError = false) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.background = isError ? '#da3633' : '#238636';
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 3000);
        }

        async function loadData() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                renderTable(data.positions, data.signals);
            } catch (err) {
                console.error(err);
            }
        }

        function renderTable(positions, signals) {
            const tbody = document.getElementById('tableBody');
            if (!positions || positions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; padding:24px; color:#8b949e;">등록된 보유 종목이 없습니다. 위 폼에서 종목을 추가해보세요!</td></tr>';
                return;
            }

            const sigMap = {};
            if (signals) {
                signals.forEach(s => { sigMap[s.code] = s; });
            }

            let html = '';
            positions.forEach((p, idx) => {
                const s = sigMap[p.code] || {};
                const isUs = p.market === 'US';
                const tagClass = isUs ? 'tag-us' : 'tag-kr';

                const buyP = p.buy_price || 0;
                const currP = s.current_price || buyP;
                const retPct = s.current_return_pct !== undefined ? s.current_return_pct : (((currP - buyP)/buyP)*100);
                const maxRet = s.max_return_pct !== undefined ? s.max_return_pct : Math.max(0, retPct);
                const stopP = s.active_stop_price || (buyP * 0.925);
                const signal = s.signal || '🟢 홀딩 (분석 대기)';
                const action = s.action_plan || '상세 지표 분석 중...';

                const buyStr = isUs ? `$${buyP.toFixed(2)}` : `${Math.round(buyP).toLocaleString()}원`;
                const currStr = isUs ? `$${currP.toFixed(2)}` : `${Math.round(currP).toLocaleString()}원`;
                const stopStr = isUs ? `$${stopP.toFixed(2)}` : `${Math.round(stopP).toLocaleString()}원`;
                const retClass = retPct >= 0 ? 'text-success' : 'text-danger';

                let badgeClass = 'badge-safe';
                if (s.urgency === 'CRITICAL') badgeClass = 'badge-critical';
                else if (s.urgency === 'WARNING') badgeClass = 'badge-warning';

                html += `
                <tr>
                    <td style="text-align:center; font-weight:bold;">${idx + 1}</td>
                    <td><span class="${tagClass}">${p.market}</span></td>
                    <td><strong>${p.name || p.code}</strong> <small style="color:#8b949e;">(${p.code})</small></td>
                    <td>${p.buy_date || '-'}</td>
                    <td style="text-align:right;">${buyStr}</td>
                    <td style="text-align:right; font-weight:bold;">${currStr}</td>
                    <td style="text-align:right;" class="${retClass}">${retPct > 0 ? '+' : ''}${retPct.toFixed(2)}%</td>
                    <td style="text-align:right;" class="text-success">+${maxRet.toFixed(1)}%</td>
                    <td><span class="badge ${badgeClass}">${signal}</span></td>
                    <td style="text-align:right; font-weight:bold;" class="text-warning">${stopStr}</td>
                    <td style="font-size:13px; max-width:260px;">${action}</td>
                    <td style="text-align:center;">
                        <button class="btn btn-danger" onclick="deleteStock('${p.code}')">삭제</button>
                    </td>
                </tr>
                `;
            });
            tbody.innerHTML = html;
        }

        async function autoLookupPrice() {
            const code = document.getElementById('inputCode').value.trim();
            const market = document.getElementById('inputMarket').value;
            if (!code) return;

            try {
                const res = await fetch(`/api/lookup?code=${encodeURIComponent(code)}&market=${market}`);
                const data = await res.json();
                if (data.success) {
                    if (data.name && !document.getElementById('inputName').value) {
                        document.getElementById('inputName').value = data.name;
                    }
                    if (data.price && !document.getElementById('inputPrice').value) {
                        document.getElementById('inputPrice').value = data.price;
                    }
                }
            } catch (e) {
                console.error(e);
            }
        }

        async function submitAddStock() {
            const code = document.getElementById('inputCode').value.trim().toUpperCase();
            const name = document.getElementById('inputName').value.trim();
            const market = document.getElementById('inputMarket').value;
            const price = parseFloat(document.getElementById('inputPrice').value);
            const date = document.getElementById('inputDate').value;
            const shares = parseInt(document.getElementById('inputShares').value) || 1;
            const memo = document.getElementById('inputMemo').value.trim();

            if (!code || isNaN(price) || price <= 0) {
                alert('종목코드와 유효한 매수가격을 입력해주세요.');
                return;
            }

            try {
                const res = await fetch('/api/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code, name: name || code, market, buy_price: price, buy_date: date, shares, memo })
                });
                const resData = await res.json();
                if (resData.success) {
                    showToast(`[${code}] 종목이 포트폴리오에 추가되었습니다!`);
                    document.getElementById('inputCode').value = '';
                    document.getElementById('inputName').value = '';
                    document.getElementById('inputPrice').value = '';
                    document.getElementById('inputMemo').value = '';
                    loadData();
                }
            } catch (err) {
                showToast('추가 중 오류 발생', true);
            }
        }

        async function deleteStock(code) {
            if (!confirm(`정말 [${code}] 종목을 포트폴리오에서 삭제하시겠습니까?`)) return;

            try {
                const res = await fetch('/api/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code })
                });
                const resData = await res.json();
                if (resData.success) {
                    showToast(`[${code}] 종목이 삭제되었습니다.`);
                    loadData();
                }
            } catch (err) {
                showToast('삭제 중 오류 발생', true);
            }
        }

        async function runSellAnalysis() {
            showToast('매도 시점 분석 및 GitHub 동기화 진행 중... 잠시만 기다려주세요.');
            try {
                const res = await fetch('/api/run_monitor', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    showToast('🎉 매도 분석 완료 및 GitHub 배포 성공!');
                    loadData();
                } else {
                    showToast('분석 실패: ' + data.error, true);
                }
            } catch (err) {
                showToast('분석 중 오류 발생', true);
            }
        }

        loadData();
    </script>
</body>
</html>
"""


KRX_NAMES: dict[str, str] = {}
US_NAMES: dict[str, str] = {}


def lookup_stock(code: str, market: str) -> dict:
    global KRX_NAMES, US_NAMES
    code = code.strip().upper()
    market = market.strip().upper()
    name = code
    price = 0.0

    if market == "KR":
        if not KRX_NAMES:
            try:
                krx = fdr.StockListing("KRX")
                for _, r in krx.iterrows():
                    c = str(r.get("Code", "")).zfill(6)
                    n = str(r.get("Name", ""))
                    if c and n:
                        KRX_NAMES[c] = n
            except Exception:
                pass
        name = KRX_NAMES.get(code.zfill(6), code)
    else:
        if not US_NAMES and os.path.exists(os.path.join("history", "latest_us.json")):
            try:
                with open(os.path.join("history", "latest_us.json"), "r", encoding="utf-8") as f:
                    ud = json.load(f)
                    for r in ud.get("df", []):
                        c = str(r.get("code", "")).upper()
                        n = str(r.get("name", ""))
                        if c and n:
                            US_NAMES[c] = n
            except Exception:
                pass
        name = US_NAMES.get(code, code)

    try:
        df = fdr.DataReader(code)
        if df is not None and not df.empty:
            price_val = float(df["Close"].dropna().iloc[-1])
            price = int(price_val) if market == "KR" else round(price_val, 2)
            return {"success": True, "name": name, "price": price}
    except Exception:
        pass

    if name != code:
        return {"success": True, "name": name, "price": price}
    return {"success": False}


class PortfolioRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

        elif path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            positions = get_portfolio()
            signals = get_sell_signals()
            self.wfile.write(json.dumps({"positions": positions, "signals": signals}, ensure_ascii=False).encode("utf-8"))

        elif path == "/api/lookup":
            qs = urllib.parse.parse_qs(parsed.query)
            code = qs.get("code", [""])[0].strip().upper()
            market = qs.get("market", ["KR"])[0].strip().upper()

            res = lookup_stock(code, market)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        data = json.loads(body) if body else {}

        if path == "/api/add":
            positions = get_portfolio()
            code = str(data.get("code", "")).strip().upper()
            market = str(data.get("market", "KR")).strip().upper()
            item = {
                "code": code,
                "name": data.get("name", code),
                "market": market,
                "buy_price": float(data.get("buy_price", 0)),
                "buy_date": data.get("buy_date", ""),
                "shares": int(data.get("shares", 1)),
                "memo": data.get("memo", ""),
            }

            existing_idx = next((i for i, p in enumerate(positions) if str(p["code"]).upper() == code), None)
            if existing_idx is not None:
                positions[existing_idx] = item
            else:
                positions.append(item)

            save_portfolio(positions)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

        elif path == "/api/delete":
            code = str(data.get("code", "")).strip().upper()
            positions = get_portfolio()
            positions = [p for p in positions if str(p["code"]).upper() != code]
            save_portfolio(positions)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

        elif path == "/api/run_monitor":
            try:
                from minervini_sell_monitor import run_sell_monitor
                from dashboard_generator import generate_unified_dashboard
                from sync_to_github import sync_all_files

                sell_signals = run_sell_monitor()

                # 캐시된 스크리닝 데이터 로드
                kr_df = pd.DataFrame()
                us_df = pd.DataFrame()
                kr_new, us_new, kr_drop, us_drop = [], [], [], []

                if os.path.exists("history/latest_kr.json"):
                    with open("history/latest_kr.json", "r", encoding="utf-8") as f:
                        kd = json.load(f)
                        kr_df = pd.DataFrame(kd.get("df", []))
                        kr_new = kd.get("new", [])
                        kr_drop = kd.get("drop", [])

                if os.path.exists("history/latest_us.json"):
                    with open("history/latest_us.json", "r", encoding="utf-8") as f:
                        ud = json.load(f)
                        us_df = pd.DataFrame(ud.get("df", []))
                        us_new = ud.get("new", [])
                        us_drop = ud.get("drop", [])

                generate_unified_dashboard(
                    kr_df=kr_df, us_df=us_df,
                    kr_new=kr_new, us_new=us_new,
                    kr_drop=kr_drop, us_drop=us_drop,
                    sell_signals=sell_signals,
                    output_path="index.html"
                )

                sync_all_files()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def run_server():
    server = HTTPServer(("127.0.0.1", PORT), PortfolioRequestHandler)
    print(f"\n=============================================================")
    print(f" 🚀 마크 미너비니 포트폴리오 웹 관리자가 실행되었습니다!")
    print(f" 👉 웹 브라우저 주소: http://127.0.0.1:{PORT}")
    print(f" (종료하려면 터미널에서 Ctrl + C 를 누르세요)")
    print(f"=============================================================\n")
    try:
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
        server.server_close()


if __name__ == "__main__":
    run_server()
