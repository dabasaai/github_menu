#!/usr/bin/env python3
"""gm — Interactive GitHub repo selector. Clone your repos from anywhere."""

import json
import os
import subprocess
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def detect_platform():
    system = sys.platform
    if system == "darwin":
        return "mac"
    if system.startswith("linux"):
        for cmd, name in [("apt", "debian"), ("yum", "rhel"), ("dnf", "fedora"), ("pacman", "arch")]:
            if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
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
    print(f"Installing gh CLI ({' '.join(cmd)})...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("Error: Failed to install gh CLI.")
        sys.exit(1)
    print("gh CLI installed successfully.\n")


def gh_get_token():
    """取得 gh 的 token，相容新舊版本。"""
    # 新版 gh >= 2.17.0 有 gh auth token
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    # 舊版用 gh auth status -t 從 stderr 解析
    result = subprocess.run(["gh", "auth", "status", "-t"], capture_output=True, text=True)
    for line in (result.stdout + result.stderr).splitlines():
        line = line.strip()
        if line.startswith("Token:"):
            return line.split(":", 1)[1].strip()
    return ""


def ensure_gh():
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("gh CLI not found.\n")
        answer = input("  Install it automatically? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            install_gh()
        else:
            print("Aborted.")
            sys.exit(1)
    # 檢查是否已登入
    status = subprocess.run(["gh", "auth", "status"], capture_output=True)
    if status.returncode != 0:
        print("gh CLI is not logged in.\n")
        print("  Running 'gh auth login'...\n")
        login_result = subprocess.run(["gh", "auth", "login"])
        if login_result.returncode != 0:
            print("Error: Login failed.")
            sys.exit(1)
    token = gh_get_token()
    if not token:
        print("Error: Could not retrieve GitHub token.")
        sys.exit(1)
    return token


def get_token():
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    return ensure_gh()


def fetch_repos(token):
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/user/repos?per_page=100&page={page}&sort=updated"
        req = Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        try:
            with urlopen(req) as resp:
                batch = json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 401:
                print("Error: Invalid or expired token.")
            else:
                print(f"Error: GitHub API returned {e.code}")
            sys.exit(1)
        if not batch:
            break
        for r in batch:
            repos.append({
                "nameWithOwner": r["full_name"],
                "description": r.get("description") or "",
                "isPrivate": r["private"],
            })
        if len(batch) < 100:
            break
        page += 1
    return repos


def display_menu(repos):
    print()
    for i, r in enumerate(repos, 1):
        private = "🔒" if r["isPrivate"] else "  "
        desc = r["description"]
        if len(desc) > 50:
            desc = desc[:47] + "..."
        print(f"  {private} {i:3d}) {r['nameWithOwner']:<40s} {desc}")
    print()


def select_owner(repos):
    owners = sorted(set(r["nameWithOwner"].split("/")[0] for r in repos))
    if len(owners) <= 1:
        return repos
    print("\n  Select account/org:\n")
    print(f"    0) All ({len(repos)} repos)")
    for i, owner in enumerate(owners, 1):
        count = sum(1 for r in repos if r["nameWithOwner"].startswith(owner + "/"))
        print(f"    {i}) {owner} ({count} repos)")
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


def main():
    clone_dest = os.getcwd()
    if len(sys.argv) > 1:
        clone_dest = os.path.abspath(sys.argv[1])
        if not os.path.isdir(clone_dest):
            print(f"Error: Directory '{clone_dest}' does not exist.")
            sys.exit(1)

    token = get_token()

    print("Fetching your GitHub repos...")
    repos = fetch_repos(token)
    if not repos:
        print("No repos found.")
        sys.exit(0)

    print(f"Found {len(repos)} repos.")
    print(f"Clone to: {clone_dest}")

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
            print(f"  Directory '{clone_dir}' already exists, skipping clone.")
        else:
            print(f"  Cloning {name} -> {clone_dir}")
            clone_url = f"https://{token}@github.com/{name}.git"
            subprocess.run(["git", "clone", clone_url, clone_dir], check=False)

        break


if __name__ == "__main__":
    main()
