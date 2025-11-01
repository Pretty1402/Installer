# README – Installer Verification Utility

## Overview
This utility verifies desktop installer readiness by performing automated pre-install checks, a simulated silent installation, and validation of the resulting layout.  
It produces detailed logs and a machine-readable JSON summary for CI/CD use.

## Features
- Supports local file paths or HTTP/HTTPS installer URLs.  
- Simulated silent installation (no UI).  
- Validation of install directory, binary, version file, and structure.  
- Clear exit codes for each failure type.  
- Timestamped log output and JSON summary report.  
- Optional `--uninstall` for idempotent reruns.  
- Minimal retry logic for network downloads (2 attempts, short backoff).  

## Requirements
- Python 3.8 or later.  
- Works on Windows or Linux.  

## Usage
Run from a terminal or CI environment.

### Basic Syntax and Expected Behaviour
```bash
python verify_desktop_installer.py \
  --build-url <path_or_http_url> \
  --app-name <application_name> \
  --install-dir <target_install_dir> \
  [--dry-run] \
  [--uninstall] \
  [--timeout <seconds>] \
  [--logs-dir <log_directory>] \
  [--summary-path <summary_json_path>]

# Verify a local installer
python verify_desktop_installer.py \
  --build-url ./sample_installer.bin \
  --app-name DemoApp \
  --install-dir ./apps/DemoApp \

# Verify an online installer
python verify_desktop_installer.py \
  --build-url https://example.com/installer.bin \
  --app-name DemoApp \
  --install-dir ./apps/DemoApp \

# Uninstall previous installation only
python verify_desktop_installer.py \
  --uninstall \
  --app-name DemoApp \
  --install-dir ./apps/DemoApp \

## How to Run
Example - Using Notepad++ Installer (Windows PowerShell)
```powershell
python verify_desktop_installer.py --build-url "https://github.com/notepad-plus-plus/notepad-plus-plus/releases/download/v8.8.7/npp.8.8.7.Installer.x64.exe" --app-name NotepadPP --install-dir .\apps --uninstall

Example - Linux
```bash
python3 verify_desktop_installer.py --build-url "https://github.com/notepad-plus-plus/notepad-plus-plus/releases/download/v8.8.7/npp.8.8.7.Installer.x64.exe" --app-name NotepadPP --install-dir ./apps --uninstall

**Expected Output**
After execution, the script creates the following:

- apps/
- bin/
- config/
- version.txt
- logs/
<timestamped_log_file>.log
- installer_summary.json

**Sample installer_summary.json**
```json
{
  "status": "success",
  "duration_seconds": 1.239,
  "log_path": "E:\\PreetiProj\\Autodesk\\Installer_utility\\Installer\\logs\\NotepadPP_20251031_232744.log",
  "checks_run": [
    "install_dir_exists",
    "binary_present",
    "version_file_present",
    "folder_structure_ok"
  ]
}

## Exit Codes
0 - Success
2 - Artifact invalid or missing
3 - Installation failure
4 - Validation failure
9 - Unexpected exception

## Repository Structure
INSTALLER/
verify_desktop_installer.py
README.md
apps/
logs/
installer_summary.json

## Notes
- Uses only Python standard libraries: argparse, pathlib, urllib, json, logging, tempfile
- No third-party dependencies required
- Designed for QA build validation and can be integrated in CI/CD pipelines using YAML configuration.
- Works cross-platform on both Windows and Linux
- Demonstrates clean, modular, and maintainable QA automation design
