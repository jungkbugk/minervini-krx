"""GitHub REST API를 이용하여 생성된 index.html (대시보드)을 GitHub 저장소에 자동 업로드/커밋하는 스크립트.

Git 프로그램이 설치되어 있지 않아도, GitHub Personal Access Token (PAT)만 있으면 동작합니다.

사용법:
  python upload_to_github.py --token <GITHUB_TOKEN> --repo <USERNAME/REPO_NAME>
또는 환경 변수 설정:
  set GITHUB_TOKEN=ghp_xxxx
  set GITHUB_REPO=myusername/my-stock-dashboard
  python upload_to_github.py
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import requests


def upload_file_to_github(
    token: str,
    repo: str,
    file_path: str = "index.html",
    target_path: str = "index.html",
    branch: str = "main",
) -> bool:
    """GitHub API를 통해 파일을 커밋(업로드)합니다."""
    if not os.path.exists(file_path):
        print(f"❌ 업로드할 파일이 존재하지 않습니다: {file_path}")
        return False

    with open(file_path, "rb") as f:
        content = f.read()

    b64_content = base64.b64encode(content).decode("utf-8")

    api_url = f"https://api.github.com/repos/{repo}/contents/{target_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 기존 파일의 SHA 조회 (기존 파일이 있으면 sha 값을 넘겨줘야 덮어쓰기 가능)
    sha = None
    r = requests.get(api_url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")

    payload = {
        "message": f"Update {target_path} (Minervini Stock Dashboard)",
        "content": b64_content,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    response = requests.put(api_url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        print(f"✅ GitHub 업로드 성공! [{repo}/{target_path}]")
        # GitHub Pages URL 안내
        username = repo.split("/")[0]
        reponame = repo.split("/")[1]
        print(f"👉 GitHub Pages 주소: https://{username}.github.io/{reponame}/")
        return True
    else:
        print(f"❌ 업로드 실패 (HTTP {response.status_code}): {response.text}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub 대시보드 자동 업로드")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub Personal Access Token")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPO"), help="GitHub 저장소 이름 (예: username/minervini-krx)")
    parser.add_argument("--file", default="index.html", help="업로드할 로컬 파일 경로 (기본: index.html)")
    parser.add_argument("--branch", default="main", help="브랜치 이름 (기본: main)")

    args = parser.parse_args()

    token = args.token
    repo = args.repo

    if not token or not repo:
        print("\n" + "=" * 60)
        print(" 📌 GitHub 대시보드 업로드 설정 안내")
        print("=" * 60)
        if not token:
            token = input("👉 GitHub Personal Access Token (토큰)을 입력하세요: ").strip()
        if not repo:
            repo = input("👉 GitHub 저장소 이름을 입력하세요 (예: myid/stock-screener): ").strip()

    if not token or not repo:
        print("⚠️ 토큰과 저장소 이름이 필요합니다.")
        sys.exit(1)

    upload_file_to_github(token=token, repo=repo, file_path=args.file, branch=args.branch)


if __name__ == "__main__":
    main()
