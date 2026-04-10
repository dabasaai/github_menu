#!/usr/bin/env python3
"""gm — Interactive GitHub/Gitea repo selector. Clone your repos from anywhere.
Compatible with Python 3.6 and below (no capture_output parameter).
"""

import json
import os
import subprocess
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

GITEA_URL = "https://gitea.gsct.tw"
GITEA_TOKEN_FILE = os.path.expanduser("~/.config/gm/gitea_token")
GM_CD_FILE = os.path.expanduser("~/.cache/gm/last_clone_dir")


def _run(cmd, **kwargs):
    """subprocess.run wrapper: convert capture_output to stdout/stderr PIPE for Python < 3.7."""
    if kwargs.pop("capture_output", False):
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    return subprocess.run(cmd, **kwargs)


def detect_platform():
    system = sys.platform
    if system == "darwin":
        return "mac"
    if system.startswith("linux"):
        for cmd, name in [("apt", "debian"), ("yum", "rhel"), ("dnf", "fedora"), ("pacman", "arch")]:
            if _run(["which", cmd], capture_output=True).returncode == 0:
                return name
        return "linux"
    return "unknown"


def install_gh():
    platform = detect_platform()
    install_cmds = {
        "mac": ["brew", "install", "gh"],
        "debian": ["sudo", "apt", "install", "-y", "gh"],
        "rhel": ["sudo", "yum", "install", "-y", "gh"],
        "fedora": ["sudo", "dnf", "install", "-y", "gh"],
        "arch": ["sudo", "pacman", "-S", "--noconfirm", "github-cli"],
    }
    if platform not in install_cmds:
        print("Error: Cannot auto-install gh on this platform.")
        print("Please install manually: https://cli.github.com")
        sys.exit(1)
    cmd = install_cmds[platform]
    print("Installing gh CLI ({0})...".format(' '.join(cmd)))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("Error: Failed to install gh CLI.")
        sys.exit(1)
    print("gh CLI installed successfully.\n")


def gh_get_token():
    """取得 gh 的 token，相容新舊版本。"""
    # 新版 gh >= 2.17.0 有 gh auth token
    result = _run(["gh", "auth", "token"], capture_output=True)
    stdout = result.stdout
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if result.returncode == 0 and stdout.strip():
        return stdout.strip()
    # 舊版用 gh auth status -t，從 stdout+stderr 找 Token 或 token
    result = _run(["gh", "auth", "status", "-t"], capture_output=True)
    out = result.stdout
    err = result.stderr
    if isinstance(out, bytes):
        out = out.decode("utf-8", errors="replace")
    if isinstance(err, bytes):
        err = err.decode("utf-8", errors="replace")
    output = out + "\n" + err
    for line in output.splitlines():
        stripped = line.strip().lstrip("✓-● ")
        if stripped.lower().startswith("token:"):
            token = stripped.split(":", 1)[1].strip()
            if token:
                return token
    # 最後嘗試從 hosts.yml 直接讀取
    hosts_file = os.path.expanduser("~/.config/gh/hosts.yml")
    if os.path.isfile(hosts_file):
        with open(hosts_file) as f:
            for line in f:
                if "oauth_token:" in line:
                    return line.split(":", 1)[1].strip()
    return ""


def gh_is_logged_in():
    """檢查 gh 是否已登入，相容新舊版本。"""
    result = _run(["gh", "auth", "status"], capture_output=True)
    out = result.stdout
    err = result.stderr
    if isinstance(out, bytes):
        out = out.decode("utf-8", errors="replace")
    if isinstance(err, bytes):
        err = err.decode("utf-8", errors="replace")
    output = out + "\n" + err
    return "Logged in" in output


def ensure_gh():
    try:
        _run(["gh", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("gh CLI not found.\n")
        answer = input("  Install it automatically? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            install_gh()
        else:
            print("Aborted.")
            sys.exit(1)
    if not gh_is_logged_in():
        print("gh CLI is not logged in.\n")
        print("  Running 'gh auth login'...\n")
        login_result = subprocess.run(["gh", "auth", "login"])
        if login_result.returncode != 0:
            print("Error: Login failed.")
            sys.exit(1)
    token = gh_get_token()
    if not token:
        print("Error: Could not retrieve GitHub token.")
        print("  Try: gh auth login --with-token")
        sys.exit(1)
    return token


def get_github_token():
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    return ensure_gh()


def get_gitea_token():
    token = os.environ.get("GITEA_TOKEN")
    if token:
        return token
    if os.path.isfile(GITEA_TOKEN_FILE):
        with open(GITEA_TOKEN_FILE) as f:
            token = f.read().strip()
        if token:
            return token
    print("\n  Gitea token 未設定（{0}）".format(GITEA_URL))
    print("  請到 Gitea > Settings > Applications > Generate New Token\n")
    token = input("  貼上 token: ").strip()
    if not token:
        print("Aborted.")
        sys.exit(1)
    os.makedirs(os.path.dirname(GITEA_TOKEN_FILE), exist_ok=True)
    with open(GITEA_TOKEN_FILE, "w") as f:
        f.write(token)
    os.chmod(GITEA_TOKEN_FILE, 0o600)
    print("  Token 已儲存至 {0}\n".format(GITEA_TOKEN_FILE))
    return token


def fetch_github_repos(token):
    repos = []
    page = 1
    while True:
        url = "https://api.github.com/user/repos?per_page=100&page={0}&sort=updated".format(page)
        req = Request(url)
        req.add_header("Authorization", "Bearer {0}".format(token))
        req.add_header("Accept", "application/vnd.github+json")
        try:
            with urlopen(req) as resp:
                batch = json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 401:
                print("Error: GitHub token invalid or expired.")
            else:
                print("Error: GitHub API returned {0}".format(e.code))
            sys.exit(1)
        if not batch:
            break
        for r in batch:
            repos.append({
                "nameWithOwner": r["full_name"],
                "description": r.get("description") or "",
                "isPrivate": r["private"],
                "source": "github",
                "clone_url": r["clone_url"],
            })
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_gitea_repos(token):
    repos = []
    page = 1
    while True:
        url = "{0}/api/v1/user/repos?limit=50&page={1}".format(GITEA_URL, page)
        req = Request(url)
        req.add_header("Authorization", "token {0}".format(token))
        try:
            with urlopen(req) as resp:
                batch = json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 401:
                print("Error: Gitea token invalid or expired.")
                if os.path.isfile(GITEA_TOKEN_FILE):
                    os.remove(GITEA_TOKEN_FILE)
                    print("  已刪除 {0}，請重新執行 gm 設定 token".format(GITEA_TOKEN_FILE))
            else:
                print("Error: Gitea API returned {0}".format(e.code))
            sys.exit(1)
        if not batch:
            break
        for r in batch:
            repos.append({
                "nameWithOwner": r["full_name"],
                "description": r.get("description") or "",
                "isPrivate": r["private"],
                "source": "gitea",
                "clone_url": r["clone_url"],
            })
        if len(batch) < 50:
            break
        page += 1
    return repos


def display_menu(repos):
    print()
    for i, r in enumerate(repos, 1):
        private = "🔒" if r["isPrivate"] else "  "
        source = "[GH]" if r.get("source") == "github" else "[GT]"
        desc = r["description"]
        if len(desc) > 50:
            desc = desc[:47] + "..."
        print("  {0} {1} {2:3d}) {3:<40s} {4}".format(private, source, i, r['nameWithOwner'], desc))
    print()


def select_owner(repos):
    owners = sorted(set(r["nameWithOwner"].split("/")[0] for r in repos))
    if len(owners) <= 1:
        return repos
    print("\n  Select account/org:\n")
    print("    0) All ({0} repos)".format(len(repos)))
    for i, owner in enumerate(owners, 1):
        count = sum(1 for r in repos if r["nameWithOwner"].startswith(owner + "/"))
        print("    {0}) {1} ({2} repos)".format(i, owner, count))
    print()
    while True:
        choice = input("  [number | q to quit]: ").strip()
        if choice.lower() == "q":
            print("Bye!")
            sys.exit(0)
        if choice.isdigit():
            idx = int(choice)
            if idx == 0:
                return repos
            if 1 <= idx <= len(owners):
                owner = owners[idx - 1]
                return [r for r in repos if r["nameWithOwner"].startswith(owner + "/")]
        print("  Invalid number, try again.")


def select_source():
    print("\n  選擇平台:\n")
    print("    1) GitHub")
    print("    2) Gitea")
    print("    3) 全部")
    print()
    while True:
        choice = input("  [1/2/3]: ").strip()
        if choice in ("1", "2", "3"):
            return int(choice)
        print("  請輸入 1, 2 或 3")


def main():
    clone_dest = os.getcwd()
    if len(sys.argv) > 1:
        clone_dest = os.path.abspath(sys.argv[1])
        if not os.path.isdir(clone_dest):
            print("Error: Directory '{0}' does not exist.".format(clone_dest))
            sys.exit(1)

    source = select_source()

    repos = []
    if source in (1, 3):
        gh_token = get_github_token()
        print("Fetching GitHub repos...")
        repos += fetch_github_repos(gh_token)

    if source in (2, 3):
        gt_token = get_gitea_token()
        print("Fetching Gitea repos...")
        repos += fetch_gitea_repos(gt_token)

    if not repos:
        print("No repos found.")
        sys.exit(0)

    print("Found {0} repos.".format(len(repos)))
    print("Clone to: {0}".format(clone_dest))

    repos = select_owner(repos)
    filtered = repos
    while True:
        display_menu(filtered)
        choice = input("  [number to clone | /keyword to search | q to quit]: ").strip()

        if choice.lower() == "q":
            print("Bye!")
            break

        if choice.startswith("/"):
            q = choice[1:].strip().lower()
            filtered = [r for r in repos if q in r["nameWithOwner"].lower() or q in r["description"].lower()]
            if not filtered:
                print("\n  No matching repos found.")
                filtered = repos
            continue

        if not choice.isdigit():
            filtered = repos
            continue

        idx = int(choice) - 1
        if idx < 0 or idx >= len(filtered):
            print("  Invalid number, try again.")
            continue

        repo = filtered[idx]
        name = repo["nameWithOwner"]
        clone_dir = os.path.join(clone_dest, name.split("/")[-1])

        if os.path.isdir(clone_dir):
            print("  Directory '{0}' already exists, skipping clone.".format(clone_dir))
        else:
            print("  Cloning {0} -> {1}".format(name, clone_dir))
            if repo.get("source") == "gitea":
                gt_token = get_gitea_token()
                clone_url = repo["clone_url"].replace("https://", "https://{0}@".format(gt_token))
            else:
                gh_token = get_github_token()
                clone_url = "https://{0}@github.com/{1}.git".format(gh_token, name)
            subprocess.run(["git", "clone", clone_url, clone_dir])

        # Write clone dir to temp file for shell wrapper to cd into
        os.makedirs(os.path.dirname(GM_CD_FILE), exist_ok=True)
        with open(GM_CD_FILE, "w") as f:
            f.write(clone_dir)
        break


if __name__ == "__main__":
    main()
