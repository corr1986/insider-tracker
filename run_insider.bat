@echo off
cd /d "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker"
call venv\Scripts\activate
python insider_tracker.py >> run.log 2>&1
