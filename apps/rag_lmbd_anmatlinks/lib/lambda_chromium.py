"""
Sparticuz Chromium on AWS Lambda (Python): extract brotli packs from a Lambda layer
(/opt/chromium) into /tmp, matching @sparticuz/chromium behaviour for Playwright.

Layer ZIP: https://github.com/Sparticuz/chromium/releases (e.g. chromium-v143.0.4-layer.x64.zip)
"""
from __future__ import annotations

import io
import os
import re
import tarfile
import tempfile
from pathlib import Path
from typing import List, Tuple

import brotli

# Sync with @sparticuz/chromium source/index.ts (graphics enabled)
_SPARTICUZ_DISABLE_FEATURES = "AudioServiceOutOfProcess,IsolateOrigins,site-per-process"
_SPARTICUZ_ENABLE_FEATURES = "SharedArrayBuffer"

_SPARTICUZ_ARGS_GRAPHICS_ON: List[str] = [
    "--ash-no-nudges",
    "--disable-domain-reliability",
    "--disable-print-preview",
    "--disk-cache-size=33554432",
    "--no-default-browser-check",
    "--no-pings",
    "--single-process",
    "--font-render-hinting=none",
    f"--disable-features={_SPARTICUZ_DISABLE_FEATURES}",
    f"--enable-features={_SPARTICUZ_ENABLE_FEATURES}",
    "--ignore-gpu-blocklist",
    "--in-process-gpu",
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--allow-running-insecure-content",
    "--disable-setuid-sandbox",
    "--disable-site-isolation-trials",
    "--disable-web-security",
    "--headless=shell",
    "--no-sandbox",
    "--no-zygote",
]

_SPARTICUZ_ARGS_GRAPHICS_OFF: List[str] = [
    "--ash-no-nudges",
    "--disable-domain-reliability",
    "--disable-print-preview",
    "--disk-cache-size=33554432",
    "--no-default-browser-check",
    "--no-pings",
    "--single-process",
    "--font-render-hinting=none",
    f"--disable-features={_SPARTICUZ_DISABLE_FEATURES}",
    f"--enable-features={_SPARTICUZ_ENABLE_FEATURES}",
    "--disable-webgl",
    "--allow-running-insecure-content",
    "--disable-setuid-sandbox",
    "--disable-site-isolation-trials",
    "--disable-web-security",
    "--headless=shell",
    "--no-sandbox",
    "--no-zygote",
]

_SUFFIX_RE = re.compile(r"\.(?:t(?:ar(?:\.(?:br|gz))?|br|gz)|br|gz)$", re.IGNORECASE)
_TAR_RE = re.compile(r"\.t(?:ar(?:\.(?:br|gz))?|br|gz)$", re.IGNORECASE)


def _strip_suffixes(name: str) -> str:
    while True:
        m = _SUFFIX_RE.search(name)
        if not m:
            return name
        name = name[: m.start()]


def _is_tar_name(name: str) -> bool:
    return bool(_TAR_RE.search(name))


def _inflate_file(file_path: Path) -> Path:
    """Decompress one Sparticuz pack file; returns primary output path (file or dir)."""
    tmp = Path(tempfile.gettempdir())
    name = file_path.name

    if "swiftshader" in name:
        out: Path = tmp
        marker = out / "libGLESv2.so"
        if marker.is_file():
            return out
    else:
        stem = _strip_suffixes(name)
        out = tmp / stem
        if out.exists() and not _is_tar_name(name):
            return out
        if out.exists() and out.is_dir() and _is_tar_name(name):
            return out

    is_tar = _is_tar_name(name)
    is_br = bool(re.search(r"br$", name, re.I))
    is_gz = name.lower().endswith(".gz")

    raw = file_path.read_bytes()
    if is_br or is_gz:
        if is_br:
            payload = brotli.decompress(raw)
        else:
            import gzip

            payload = gzip.decompress(raw)
    else:
        payload = raw

    if is_tar:
        out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as tf:
            # Trusted Sparticuz payloads; tarfile filter requires Python 3.12+.
            tf.extractall(out)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
        out.chmod(0o700)

    return out


def _lambda_should_extract_al2023() -> bool:
    ex = os.environ.get("AWS_EXECUTION_ENV", "")
    if not ex.startswith("AWS_Lambda_python"):
        return False
    # Python 3.11+ runtimes use Amazon Linux 2023
    ver = ex.removeprefix("AWS_Lambda_python")
    parts = ver.split(".")
    if len(parts) < 2:
        return True
    try:
        major, minor = int(parts[0]), int(parts[1])
        return major > 3 or (major == 3 and minor >= 11)
    except ValueError:
        return True


def _setup_lambda_env_after_extract() -> None:
    tmp = tempfile.gettempdir()
    base_lib = str(Path(tmp) / "al2023" / "lib")
    os.environ.setdefault("FONTCONFIG_PATH", str(Path(tmp) / "fonts"))
    os.environ.setdefault("HOME", tmp)
    if not Path(base_lib).is_dir():
        return
    cur = os.environ.get("LD_LIBRARY_PATH", "")
    if not cur:
        os.environ["LD_LIBRARY_PATH"] = base_lib
    elif not cur.startswith(base_lib):
        os.environ["LD_LIBRARY_PATH"] = f"{base_lib}:{cur}"


def sparticuz_chromium_args() -> List[str]:
    if os.environ.get("CHROMIUM_GRAPHICS_MODE", "true").lower() in ("0", "false", "no"):
        return list(_SPARTICUZ_ARGS_GRAPHICS_OFF)
    return list(_SPARTICUZ_ARGS_GRAPHICS_ON)


def ensure_sparticuz_executable(pack_dir: str | None = None) -> Tuple[str, List[str]]:
    """
    If pack_dir contains chromium.br (Lambda layer at /opt/chromium), extract to /tmp
    and return (executable_path, chromium_argv). Otherwise raises FileNotFoundError.
    """
    base = Path(pack_dir) if pack_dir else (_discover_pack_dir() or Path("/opt/chromium"))
    chromium_br = base / "chromium.br"
    if not chromium_br.is_file():
        raise FileNotFoundError(f"No Sparticuz pack at {chromium_br}")

    exe = Path(tempfile.gettempdir()) / "chromium"
    if exe.is_file():
        _setup_lambda_env_after_extract()
        return str(exe), sparticuz_chromium_args()

    graphics_on = os.environ.get("CHROMIUM_GRAPHICS_MODE", "true").lower() not in (
        "0",
        "false",
        "no",
    )

    jobs: List[Path] = [chromium_br, base / "fonts.tar.br"]
    if graphics_on:
        jobs.append(base / "swiftshader.tar.br")
    if _lambda_should_extract_al2023():
        al = base / "al2023.tar.br"
        if al.is_file():
            jobs.append(al)

    for p in jobs:
        if p.is_file():
            _inflate_file(p)

    _setup_lambda_env_after_extract()

    if not exe.is_file():
        raise RuntimeError(f"Chromium binary missing after extract: {exe}")

    return str(exe), sparticuz_chromium_args()


def _discover_pack_dir() -> Path | None:
    """
    Official Sparticuz *-layer.x64.zip installs packs at:
      /opt/nodejs/node_modules/@sparticuz/chromium/bin/
    (not bin/x64). Some builds use /opt/chromium.
    """
    explicit = os.environ.get("CHROMIUM_PACK_PATH")
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(
        [
            Path("/opt/nodejs/node_modules/@sparticuz/chromium/bin"),
            Path("/opt/nodejs/node_modules/@sparticuz/chromium/bin/x64"),
            Path("/opt/nodejs/node_modules/@sparticuz/chromium/bin/arm64"),
            Path("/opt/chromium"),
        ]
    )
    seen: set[str] = set()
    for base in candidates:
        key = str(base)
        if key in seen:
            continue
        seen.add(key)
        if (base / "chromium.br").is_file():
            return base

    opt = Path("/opt")
    if opt.is_dir():
        for found in opt.rglob("chromium.br"):
            if found.is_file():
                return found.parent
    return None


def try_sparticuz_launch_config() -> Tuple[str | None, List[str] | None]:
    """Returns (executable_path, args) for Sparticuz layer, or (None, None) for stock Playwright."""
    base = _discover_pack_dir()
    if base is None:
        return None, None
    try:
        path, args = ensure_sparticuz_executable(str(base))
        return path, args
    except OSError:
        return None, None
