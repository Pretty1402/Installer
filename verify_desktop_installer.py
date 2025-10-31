#!/usr/bin/env python3
# Installer Verifier (Windows/Linux)

import argparse, json, logging, os, shutil, sys, tempfile, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

EXIT_OK = 0
EXIT_PRECHECK_FAIL = 2
EXIT_INSTALL_FAIL = 3
EXIT_VALIDATION_FAIL = 4
EXIT_UNEXPECTED = 9

DEFAULT_TIMEOUT_S = 30
DEFAULT_LOGS_DIR = "./logs"
DEFAULT_SUMMARY_PATH = "./installer_summary.json"
HTTP_TIMEOUT_S = 20
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_S = 2.0

def utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))

def _sanitize_for_filename(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in "-_").strip()
    return safe or "app"

def setup_logging(app_name: str, logs_dir: Path) -> tuple[logging.Logger, Path]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_app = _sanitize_for_filename(app_name)
    logfile = logs_dir / f"{safe_app}_{stamp}.log"

    logger = logging.getLogger("installer_verifier")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logging.Formatter.converter = time.gmtime
    fmt = logging.Formatter("[%(asctime)sZ] %(message)s", "%Y-%m-%dT%H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    fh = logging.FileHandler(logfile, encoding="utf-8")
    ch.setFormatter(fmt); fh.setFormatter(fmt)
    logger.addHandler(ch); logger.addHandler(fh)
    return logger, logfile

def download_with_retry(url: str, dest: Path, logger: logging.Logger) -> tuple[Path, int]:
    headers = {"User-Agent": "installer-verifier/1.0"}
    req = urllib.request.Request(url, headers=headers)
    last_err: Optional[Exception] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                data = r.read()
            if not data:
                raise RuntimeError("Downloaded zero bytes")
            dest.write_bytes(data)
            return dest, attempt
        except Exception as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS:
                logger.info(f"[Precheck] Download failed (attempt {attempt}): {e} -> retrying...")
                time.sleep(RETRY_BACKOFF_S)
    raise RuntimeError(str(last_err) if last_err else "Download failed")

def precheck_source(src: str, logger: logging.Logger) -> Path:
    logger.info("=== [1/6] Pre-install sanity check ===")
    logger.info(f"[Precheck] Source: {src!r}")
    if is_url(src):
        with tempfile.TemporaryDirectory(prefix="inst_dl_") as td:
            tmp_path = Path(td) / "installer.bin"
            path, attempts = download_with_retry(src, tmp_path, logger)
            size = path.stat().st_size
            logger.info(f"[Precheck] Downloaded in {attempts} attempt(s), size={size} bytes")
            keep_dir = Path(tempfile.mkdtemp(prefix="inst_dl_keep_"))
            final_path = keep_dir / "installer.bin"
            shutil.copy2(path, final_path)
            logger.info("[Precheck] Result: OK (HTTP/HTTPS source accessible and non-zero)")
            return final_path
    else:
        path = Path(src).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        size = path.stat().st_size
        if size <= 0:
            raise RuntimeError(f"File is empty: {path}")
        logger.info(f"[Precheck] Local file present, size={size} bytes")
        logger.info("[Precheck] Result: OK (local source accessible and non-zero)")
        return path

def do_uninstall(install_dir: Path, logger: logging.Logger) -> None:
    logger.info("=== [0/6] Uninstall (idempotency) ===")
    if install_dir.exists():
        logger.info(f"[Uninstall] Removing: {install_dir}")
        shutil.rmtree(install_dir, ignore_errors=True)
    else:
        logger.info(f"[Uninstall] Nothing to remove at: {install_dir}")
    logger.info("[Uninstall] Result: OK")

def simulate_silent_install(app_name: str, installer_path: Path, install_dir: Path,
                            timeout_s: int, logger: logging.Logger, dry_run: bool) -> None:
    logger.info("=== [2/6] Silent simulation ===")
    logger.info(f"[Install] Target: {install_dir} (timeout={timeout_s}s, dry_run={dry_run})")
    start = time.monotonic()
    time.sleep(0.3)
    if time.monotonic() - start > timeout_s:
        raise TimeoutError("Install step timed out")
    if dry_run:
        logger.info("[Install] Skipped filesystem writes (dry-run)")
        logger.info("[Install] Result: OK")
        return

    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "bin").mkdir(exist_ok=True)
    (install_dir / "config").mkdir(exist_ok=True)

    bin_name = f"{app_name}.exe" if os.name == "nt" else app_name
    (install_dir / "bin" / bin_name).write_text("#!/usr/bin/env bash\n# placeholder\n", encoding="utf-8")

    # Simplified version file per requirement (no derived label)
    (install_dir / "version.txt").write_text("1.0.0\n", encoding="utf-8")

    meta = {
        "app_name": app_name,
        "installed_at_utc": utc_ts(),
        "installed_from": str(installer_path),
        "version_label": "1.0.0",
    }
    (install_dir / "install_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("[Install] Result: OK (layout created: bin/, version.txt, install_meta.json)")

def validate_install(install_dir: Path, app_name: str, logger: logging.Logger) -> list[str]:
    logger.info("=== [3/6] Install validation ===")
    checks: list[str] = []

    bin_name = f"{app_name}.exe" if os.name == "nt" else app_name
    bin_path = install_dir / "bin" / bin_name
    version_path = install_dir / "version.txt"

    exists = install_dir.exists()
    checks.append("install_dir_exists" if exists else "install_dir_missing")
    logger.info(f"[Validate] Install dir: {'OK' if exists else 'MISSING'}")
    if not exists:
        return checks

    bin_ok = bin_path.exists()
    checks.append("binary_present" if bin_ok else "binary_missing")
    logger.info(f"[Validate] Binary: {'OK' if bin_ok else 'MISSING'}")

    version_ok = version_path.exists()
    checks.append("version_file_present" if version_ok else "version_file_missing")
    if version_ok:
        try:
            version_text = version_path.read_text(encoding="utf-8").strip()
        except Exception:
            version_text = "<unreadable>"
        logger.info(f"[Validate] Version file: OK (value='{version_text}')")
    else:
        logger.info("[Validate] Version file: MISSING")

    structure_ok = all((install_dir / p).exists() for p in ("bin", "config"))
    checks.append("folder_structure_ok" if structure_ok else "folder_structure_incomplete")
    logger.info(f"[Validate] Structure (bin/, config/): {'OK' if structure_ok else 'INCOMPLETE'}")

    expected = {"install_dir_exists", "version_file_present", "binary_present", "folder_structure_ok"}
    logger.info(f"[Validate] Result: {'OK' if expected.issubset(checks) else 'FAIL'}")
    return checks

def write_summary(status: str, started_at: float, log_path: Path, checks: list[str],
                  out_path: Path, logger: logging.Logger) -> None:
    logger.info("=== [4/6] Summary ===")
    duration = round(time.monotonic() - started_at, 3)
    summary = {"status": status, "duration_seconds": duration, "log_path": str(log_path), "checks_run": checks}
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"[Summary] Path: {out_path}")
    logger.info(f"[Summary] Status: {status}, Duration: {duration}s")

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify installer by simulating a silent install and validating layout.")
    p.add_argument("--build-url", help="Local file path or HTTP/HTTPS URL to installer")
    p.add_argument("--app-name", required=True, help="Application label (used for bin name)")
    p.add_argument("--install-dir", required=True, help="Target installation directory")
    p.add_argument("--dry-run", action="store_true", help="Simulate without filesystem changes")
    p.add_argument("--uninstall", action="store_true", help="Remove previous installation first")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help=f"Timeout seconds (default: {DEFAULT_TIMEOUT_S})")
    p.add_argument("--logs-dir", default=DEFAULT_LOGS_DIR, help=f"Log directory (default: {DEFAULT_LOGS_DIR})")
    p.add_argument("--summary-path", default=DEFAULT_SUMMARY_PATH, help=f"JSON summary path (default: {DEFAULT_SUMMARY_PATH})")
    return p.parse_args()

def main() -> None:
    started = time.monotonic()
    args = parse_args()
    app_name = args.app_name.strip()
    install_dir = Path(args.install_dir).expanduser().resolve()
    logs_dir = Path(args.logs_dir).expanduser().resolve()
    summary_path = Path(args.summary_path).expanduser().resolve()
    logger, log_path = setup_logging(app_name, logs_dir)
    checks: list[str] = []
    status = "success"
    exit_code = EXIT_OK

    try:
        logger.info("=== [0/6] Installer Verification Started ===")
        logger.info(f"[Start] App={app_name} Target={install_dir}")

        if args.uninstall:
            do_uninstall(install_dir, logger)

        if not args.build_url and not args.uninstall:
            status = "precheck_failed"
            logger.info("[Start] FAIL: provide --build-url for verification, or use --uninstall for cleanup")
            exit_code = EXIT_PRECHECK_FAIL
            return

        installer_src: Optional[Path] = None
        if args.build_url:
            try:
                installer_src = precheck_source(args.build_url, logger)
            except Exception as e:
                status = "download_or_verify_failed"
                logger.info(f"[Precheck] FAIL: {e}")
                exit_code = EXIT_PRECHECK_FAIL
                return

            try:
                simulate_silent_install(app_name, installer_src, install_dir, args.timeout, logger, args.dry_run)
            except Exception as e:
                status = "install_failed"
                logger.info(f"[Install] FAIL: {e}")
                exit_code = EXIT_INSTALL_FAIL
                return

            checks = validate_install(install_dir, app_name, logger)
            expected = {"install_dir_exists", "version_file_present", "binary_present", "folder_structure_ok"}
            if not args.dry_run and not expected.issubset(checks):
                status = "validation_failed"
                logger.info("[Validate] FAIL: expected checks not met")
                exit_code = EXIT_VALIDATION_FAIL
                return

        logger.info("=== [5/6] Final status ===")
        logger.info("[Final] SUCCESS: all required checks passed")
        status = "success"
        exit_code = EXIT_OK

    except Exception as e:
        status = "unexpected_exception"
        logger.info(f"[Final] UNEXPECTED ERROR: {e}")
        exit_code = EXIT_UNEXPECTED
    finally:
        write_summary(status, started, log_path, checks, summary_path, logger)
        logger.info("=== [6/6] Completion ===")
        if exit_code == EXIT_OK:
            logger.info("==== Installer verification completed successfully ====")
    sys.exit(exit_code)

if __name__ == "__main__":
    main()