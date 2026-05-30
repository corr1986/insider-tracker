"""
Sync Obsidian portfolio markdown from GitHub.

Runs on PC startup via Task Scheduler:
  python sync_obsidian.py

1. git pull to get latest portfolio.json and Portfolio Simulato.md from GitHub Actions
2. Regenerates Portfolio Simulato.md in the local Obsidian vault
"""
import subprocess
import shutil
from pathlib import Path

REPO_DIR = Path(__file__).parent
REPO_MD = REPO_DIR / "Portfolio Simulato.md"
OBSIDIAN_MD = REPO_DIR.parent / "Portfolio Simulato.md"

def main():
    print("Pulling latest from GitHub...")
    result = subprocess.run(
        ["git", "pull"],
        cwd=REPO_DIR,
        capture_output=True, text=True
    )
    print(result.stdout or result.stderr)

    if REPO_MD.exists():
        shutil.copy2(REPO_MD, OBSIDIAN_MD)
        print(f"Copied to Obsidian: {OBSIDIAN_MD}")
    else:
        print("Portfolio Simulato.md not yet in repo — will appear after first GitHub Actions run.")

if __name__ == "__main__":
    main()
