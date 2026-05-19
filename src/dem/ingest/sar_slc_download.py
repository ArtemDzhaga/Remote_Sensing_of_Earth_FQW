# -*- coding: utf-8 -*-
"""
Загрузка Sentinel-1 SLC по региону и датам (ASF Search + datapool).

Поиск сцен — ASF API. Скачивание — HTTPS; сервер требует вход в NASA Earthdata.

Рекомендуемый способ (пакет earthaccess в requirements.txt):

1. Зарегистрироваться: https://urs.earthdata.nasa.gov/
2. Один из вариантов:
   - запись в ``~/.netrc`` (предпочтительно; пароль не попадает в командную строку), или
   - переменная ``EARTHDATA_TOKEN``::

       machine urs.earthdata.nasa.gov
         login <username>
         password <password>

3. Установка: ``pip install -r requirements.txt``

Флаг ``--auth interactive`` — один раз ввести логин/пароль в терминале (earthaccess).

Важно: команды в терминале разделяйте переводом строки. Нельзя писать
``pip install -r requirements.txtexport EARTHDATA_TOKEN=...`` в одну строку —
тогда ``export`` не выполнится.

Если после входа всё ещё 403 и в ответе есть ``eula`` — примите условия для
Alaska Satellite Facility в профиле Earthdata.

При **HTTP 401** на ``datapool.asf.alaska.edu`` чаще всего нужно в профиле Earthdata
(**Applications**) разрешить доступ приложению **Alaska Satellite Facility** и при
необходимости сгенерировать новый токен на https://urs.earthdata.nasa.gov/ —
не подставляйте произвольный JWT из браузера, если это не токен из раздела Earthdata.

Если задан только ``EARTHDATA_TOKEN``, а 401 сохраняется, используйте ``~/.netrc``
для того же аккаунта; скрипт также поддерживает ``EARTHDATA_USERNAME`` +
``EARTHDATA_PASSWORD``, но не рекомендуется вводить пароль как shell-команду.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import requests

from dem.ingest.asf_slc import SlcScene, fetch_slc_scenes
from dem.config import DEFAULT_REGION, REGIONS
from dem.io.layout import resolve_out_dir, slc_runs_dir

REQUEST_TIMEOUT = (30, 180)  # connect timeout, read timeout (seconds)
DOWNLOAD_MAX_ATTEMPTS = 20


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")


def _session_basic_netrc() -> requests.Session:
    s = requests.Session()
    user = os.environ.get("EARTHDATA_USERNAME", "").strip()
    pw = os.environ.get("EARTHDATA_PASSWORD", "").strip()
    if user and pw:
        s.auth = (user, pw)
        return s
    try:
        import netrc

        nrc = netrc.netrc()
        auth = nrc.authenticators("urs.earthdata.nasa.gov")
        if auth:
            login, _, password = auth
            if login and password:
                s.auth = (login, password)
    except (FileNotFoundError, OSError, netrc.NetrcParseError):
        pass
    return s


def _make_session(auth_mode: str) -> requests.Session:
    if auth_mode == "basic":
        return _session_basic_netrc()

    try:
        import earthaccess
        from earthaccess.exceptions import LoginAttemptFailure
    except ImportError:
        if auth_mode in ("interactive", "environment", "netrc"):
            raise SystemExit("Установите earthaccess: pip install earthaccess") from None
        print("Для надёжного доступа к ASF datapool установите earthaccess: pip install earthaccess.", file=sys.stderr)
        return _session_basic_netrc()

    if auth_mode == "interactive":
        earthaccess.login(strategy="interactive")
        return earthaccess.get_requests_https_session()
    if auth_mode == "environment":
        earthaccess.login(strategy="environment")
        return earthaccess.get_requests_https_session()
    if auth_mode == "netrc":
        earthaccess.login(strategy="netrc")
        return earthaccess.get_requests_https_session()

    # auto
    for strat in ("environment", "netrc"):
        try:
            earthaccess.login(strategy=strat)
            return earthaccess.get_requests_https_session()
        except LoginAttemptFailure:
            continue
    return _session_basic_netrc()


def _earthaccess_strategy(auth_mode: str) -> str:
    if auth_mode == "interactive":
        return "interactive"
    if auth_mode == "environment":
        return "environment"
    if auth_mode == "netrc":
        return "netrc"
    return "all"


def _earthaccess_login_for_download(auth_mode: str) -> bool:
    """Вызов earthaccess.login; вернуть True, если доступна earthaccess-сессия."""

    try:
        import earthaccess
        from earthaccess.exceptions import LoginAttemptFailure, LoginStrategyUnavailable
    except ImportError:
        if auth_mode in ("interactive", "environment", "netrc"):
            raise SystemExit("Установите earthaccess: pip install earthaccess") from None
        print(
            "earthaccess не установлен; --auth auto переключается на HTTP basic через ~/.netrc "
            "или EARTHDATA_USERNAME/EARTHDATA_PASSWORD.",
            file=sys.stderr,
        )
        return False

    strat = _earthaccess_strategy(auth_mode)

    if strat == "interactive":
        if not sys.stdin.isatty():
            raise SystemExit(
                "--auth interactive нужен интерактивный терминал. "
                "Иначе: EARTHDATA_TOKEN / ~/.netrc и --auth auto или --auth netrc."
            )
        earthaccess.login(strategy="interactive")
        return True

    if strat in ("environment", "netrc"):
        earthaccess.login(strategy=strat)
        return True

    # auto → strat == "all"
    if sys.stdin.isatty():
        earthaccess.login(strategy="all")
        return True

    for sub in ("environment", "netrc"):
        try:
            earthaccess.login(strategy=sub)
            if getattr(earthaccess.__auth__, "authenticated", False):
                return True
        except LoginStrategyUnavailable:
            continue
        except LoginAttemptFailure as e:
            raise SystemExit(f"Earthdata отклонил вход ({sub}): {e}") from e

    raise SystemExit(
        "Неинтерактивный режим: не заданы учётные данные Earthdata. "
        "Укажите EARTHDATA_TOKEN (или EARTHDATA_USERNAME + EARTHDATA_PASSWORD), либо ~/.netrc "
        "для machine urs.earthdata.nasa.gov — см. описание в начале sar_slc_download.py."
    )


def _earthaccess_requests_session_fallback() -> requests.Session:
    """Та же авторизация, что у earthaccess.download (не новый логин через ``auto``)."""

    try:
        import earthaccess
    except ImportError:
        return _make_session("auto")

    try:
        return earthaccess.get_requests_https_session()
    except Exception:
        return _make_session("auto")


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "unknown"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def _parse_content_range(value: str) -> int | None:
    """Вернуть общий размер из `Content-Range: bytes start-end/total`."""

    if not value:
        return None
    m = re.search(r"/(\d+)\s*$", value)
    return int(m.group(1)) if m else None


def _download_via_earthaccess(url: str, dest: Path) -> None:
    import earthaccess

    dest.parent.mkdir(parents=True, exist_ok=True)
    print("  earthaccess: start download (progress may appear below)", flush=True)
    paths = earthaccess.download(
        [url],
        str(dest.parent),
        threads=1,
        show_progress=True,
        pqdm_kwargs={"disable": False, "n_jobs": 1},
    )
    if not paths:
        raise RuntimeError("earthaccess.download не вернул файлов.")
    got = paths[0]
    if got.resolve() != dest.resolve():
        if dest.exists():
            dest.unlink()
        got.rename(dest)


def _download_file_once(session: requests.Session, url: str, dest: Path, *, chunk: int = 1024 * 1024) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    user = os.environ.get("EARTHDATA_USERNAME", "").strip()
    pw = os.environ.get("EARTHDATA_PASSWORD", "").strip()

    existing = dest.stat().st_size if dest.exists() else 0
    req_headers: dict[str, str] = {}
    # Не дублировать Authorization, если сессия earthaccess уже Bearer-подписана.
    if token and not (session.headers.get("Authorization") or "").strip():
        req_headers["Authorization"] = f"Bearer {token}"
    if existing > 0:
        req_headers["Range"] = f"bytes={existing}-"

    print("  http: start download" + (f" (resume from {_fmt_bytes(existing)})" if existing else ""), flush=True)
    r = session.get(url, stream=True, timeout=REQUEST_TIMEOUT, headers=req_headers or None, allow_redirects=True)
    try:
        if existing > 0 and r.status_code != 206:
            print("  http: server did not accept resume; restarting from 0", flush=True)
            existing = 0
        if r.status_code == 401 and token and req_headers:
            r.close()
            plain = requests.Session()
            print("  http: retry with bearer token", flush=True)
            headers = {"Authorization": f"Bearer {token}"}
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
            r = plain.get(
                url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                headers=headers,
                allow_redirects=True,
            )
        if r.status_code == 401 and user and pw:
            r.close()
            print("  http: retry with username/password", flush=True)
            headers = {"Range": f"bytes={existing}-"} if existing > 0 else None
            r = requests.Session().get(
                url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                headers=headers,
                auth=(user, pw),
                allow_redirects=True,
            )
        if r.status_code in (401, 403):
            body = (r.text or "")[:500].lower()
            hint = ""
            if "eula" in body:
                hint = "\nПохоже на непринятое EULA: в профиле Earthdata примите доступ к ASF / Sentinel."
            raise RuntimeError(
                f"HTTP {r.status_code}: нет доступа к ASF datapool.{hint}\n"
                "Частые причины 401:\n"
                "  • В Earthdata (Applications) не подключено приложение Alaska Satellite Facility.\n"
                "  • Нужен свежий токен с https://urs.earthdata.nasa.gov/ (раздел токенов Earthdata Login).\n"
                "  • Вместо токена используйте ~/.netrc для urs.earthdata.nasa.gov.\n"
                "Дополнительно:\n"
                "  • export EARTHDATA_TOKEN=... отдельной строкой в shell.\n"
                "  • --auth interactive в обычном терминале или ~/.netrc для urs.earthdata.nasa.gov.\n"
                "Регистрация и приложения: https://urs.earthdata.nasa.gov/"
            )
        r.raise_for_status()
        total_header = r.headers.get("content-length", "").strip()
        total = _parse_content_range(r.headers.get("content-range", ""))
        if total is None and total_header.isdigit():
            total = int(total_header) + existing if r.status_code == 206 else int(total_header)
        downloaded = existing
        last_report = time.monotonic()
        start_report = last_report
        start_downloaded = downloaded
        print(f"  http: size={_fmt_bytes(total)}", flush=True)
        print("  http: waiting for first chunk...", flush=True)
        first_chunk = True
        mode = "ab" if existing > 0 and r.status_code == 206 else "wb"
        if mode == "wb":
            downloaded = 0
        with open(dest, mode) as f:
            for part in r.iter_content(chunk_size=chunk):
                if part:
                    if first_chunk:
                        print("  http: first chunk received", flush=True)
                        first_chunk = False
                    f.write(part)
                    downloaded += len(part)
                    now = time.monotonic()
                    if now - last_report >= 5:
                        rate = (downloaded - start_downloaded) / max(now - start_report, 1e-6)
                        rate_s = f"{_fmt_bytes(int(rate))}/s"
                        if total:
                            pct = downloaded / total * 100
                            eta = int((total - downloaded) / rate) if rate > 0 else -1
                            eta_s = f", eta~{eta // 60}m{eta % 60:02d}s" if eta >= 0 else ""
                            print(
                                f"  http: {_fmt_bytes(downloaded)} / {_fmt_bytes(total)} ({pct:.1f}%, {rate_s}{eta_s})",
                                flush=True,
                            )
                        else:
                            print(f"  http: {_fmt_bytes(downloaded)} downloaded ({rate_s})", flush=True)
                        last_report = now
        if total:
            print(f"  http: done {_fmt_bytes(downloaded)} / {_fmt_bytes(total)}", flush=True)
        else:
            print(f"  http: done {_fmt_bytes(downloaded)}", flush=True)
        return total is None or downloaded >= total
    finally:
        r.close()


def _download_file(session: requests.Session, url: str, dest: Path, *, chunk: int = 1024 * 1024) -> None:
    """Скачать файл с resume/retry на сетевых обрывах."""

    for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
        try:
            if attempt > 1:
                size = dest.stat().st_size if dest.exists() else 0
                print(f"  http: retry attempt {attempt}/{DOWNLOAD_MAX_ATTEMPTS}, local={_fmt_bytes(size)}", flush=True)
            complete = _download_file_once(session, url, dest, chunk=chunk)
            if complete:
                return
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError) as e:
            size = dest.stat().st_size if dest.exists() else 0
            print(
                f"  http: network interruption ({type(e).__name__}); saved={_fmt_bytes(size)}, will resume",
                flush=True,
            )
            if attempt == DOWNLOAD_MAX_ATTEMPTS:
                raise
            time.sleep(min(30, attempt * 2))
            continue
    raise RuntimeError(f"Не удалось скачать {url} за {DOWNLOAD_MAX_ATTEMPTS} попыток")


def _scene_from_manifest_row(row: dict) -> SlcScene:
    names = {f.name for f in fields(SlcScene)}
    return SlcScene(**{k: row[k] for k in names if k in row})


def cmd_list(args: argparse.Namespace) -> None:
    region = REGIONS[args.region]
    scenes = fetch_slc_scenes(
        region=region,
        date_from=args.date_from,
        date_to=args.date_to,
        max_results=args.max_results,
        beam_mode="IW",
    )
    lim = args.limit if args.limit > 0 else len(scenes)
    for s in scenes[:lim]:
        print(f"- {s.file_id} | {s.start_time} | {s.download_url}")
    print(f"Total scenes: {len(scenes)} (shown {min(lim, len(scenes))})")


def cmd_download(args: argparse.Namespace) -> None:
    region_key = args.region
    date_from = args.date_from
    date_to = args.date_to
    if getattr(args, "from_manifest", "").strip():
        mp = Path(args.from_manifest.strip()).expanduser()
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        rows = manifest.get("scenes")
        if not isinstance(rows, list) or not rows:
            raise SystemExit(f"В манифесте нет списка scenes: {mp}")
        scenes = [_scene_from_manifest_row(x) for x in rows if isinstance(x, dict)]
        region_key = str(manifest.get("region") or region_key)
        date_from = str(manifest.get("date_from") or date_from)
        date_to = str(manifest.get("date_to") or date_to)
        if region_key not in REGIONS:
            raise SystemExit(f"Неизвестный регион в манифесте: {region_key}")
        if not date_from or not date_to:
            raise SystemExit("Укажите date_from/date_to в манифесте или передайте --date-from/--date-to.")
    else:
        if not date_from or not date_to:
            raise SystemExit("Нужны --date-from и --date-to (или --from-manifest с датами в JSON).")
        scenes = fetch_slc_scenes(
            region=REGIONS[region_key],
            date_from=date_from,
            date_to=date_to,
            max_results=args.max_results,
            beam_mode="IW",
        )
    if not scenes:
        print("No SLC scenes found for this region and period.")
        return

    if args.file_id:
        wanted = [needle.strip() for needle in args.file_id if needle.strip()]
        filtered: list[SlcScene] = []
        for needle in wanted:
            matches = [s for s in scenes if needle in s.file_id]
            if not matches:
                raise SystemExit(f"Не найдена SLC scene по --file-id {needle!r}")
            filtered.extend(matches)
        # Preserve --file-id order, remove duplicates.
        seen: set[str] = set()
        scenes = [s for s in filtered if not (s.file_id in seen or seen.add(s.file_id))]

    out_base = resolve_out_dir(args.out_dir, slc_runs_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = out_base / f"slc_{region_key}_{date_from}_{date_to}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    if getattr(args, "from_manifest", "").strip():
        n = len(scenes)
    else:
        n = args.limit if args.limit > 0 else len(scenes)
    to_get = scenes[:n]

    has_env_credentials = bool(os.environ.get("EARTHDATA_TOKEN", "").strip()) or (
        bool(os.environ.get("EARTHDATA_USERNAME", "").strip())
        and bool(os.environ.get("EARTHDATA_PASSWORD", "").strip())
    )
    if args.auth != "basic" and not has_env_credentials:
        if args.auth == "environment":
            print(
                "Для --auth environment нужен EARTHDATA_TOKEN или EARTHDATA_USERNAME/EARTHDATA_PASSWORD "
                "в окружении этой shell-сессии. Для обычной работы предпочтителен --auth netrc.",
                file=sys.stderr,
            )

    session = _make_session(args.auth) if args.auth == "basic" else None
    use_earthaccess = False
    if args.auth != "basic":
        use_earthaccess = _earthaccess_login_for_download(args.auth)
        if not use_earthaccess:
            session = _make_session("auto")

    manifest = {
        "region": region_key,
        "date_from": date_from,
        "date_to": date_to,
        "run_dir": run_dir.as_posix(),
        "auth_mode": args.auth,
        "scenes": [s.__dict__ for s in to_get],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for i, s in enumerate(to_get, start=1):
        name = _slug(s.file_id) + ".zip"
        dest = run_dir / name
        print(f"[{i}/{len(to_get)}] {s.file_id}", flush=True)
        print(f"  url: {s.download_url}", flush=True)
        print(f"  -> {dest}", flush=True)
        if args.auth != "basic":
            # Низкоуровневый HTTP даёт прогресс по байтам; earthaccess tqdm
            # показывает только "0/1 file" и выглядит как зависание на больших SLC.
            fb = _earthaccess_requests_session_fallback() if use_earthaccess else session
            _download_file(fb, s.download_url, dest)
        else:
            _download_file(session, s.download_url, dest)
    print(f"Done: {run_dir}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Список и загрузка Sentinel-1 SLC (ASF).")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    common.add_argument("--date-from", type=str, required=True, help="YYYY-MM-DD")
    common.add_argument("--date-to", type=str, required=True, help="YYYY-MM-DD")
    common.add_argument("--max-results", type=int, default=200, help="Максимум сцен из ASF (поиск).")

    dl_common = argparse.ArgumentParser(add_help=False)
    dl_common.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    dl_common.add_argument("--date-from", type=str, default="", help="YYYY-MM-DD (не нужно при --from-manifest, если даты есть в JSON).")
    dl_common.add_argument("--date-to", type=str, default="", help="YYYY-MM-DD")
    dl_common.add_argument("--max-results", type=int, default=200, help="Максимум сцен из ASF (поиск).")

    ls = sub.add_parser("list", parents=[common], help="Список сцен без скачивания.")
    ls.add_argument("--limit", type=int, default=20, help="Сколько строк показать. 0 = все.")
    ls.set_defaults(func=cmd_list)

    dl = sub.add_parser("download", parents=[dl_common], help="Скачать первые N сцен (по времени).")
    dl.add_argument(
        "--limit",
        "--max-scenes",
        dest="limit",
        type=int,
        default=1,
        help="Сколько архивов скачать (по порядку времени). 0 = все найденные.",
    )
    dl.add_argument(
        "--out-dir",
        type=str,
        default="",
        help="Пусто = outputs/<дата>/data/raw/slc_runs (см. io_layout.py, VKR_RUN_DATE).",
    )
    dl.add_argument(
        "--from-manifest",
        type=str,
        default="",
        help="JSON от dem.ingest.slc_budget_plan: скачать список scenes без повторного ASF-поиска.",
    )
    dl.add_argument(
        "--file-id",
        action="append",
        default=[],
        help="Скачать конкретную сцену по полному или частичному fileID; можно повторять.",
    )
    dl.add_argument(
        "--auth",
        type=str,
        default="auto",
        choices=["auto", "interactive", "environment", "netrc", "basic"],
        help=(
            "auto: earthaccess (environment→netrc), иначе только HTTP basic из netrc/env; "
            "interactive: запрос логина в терминале."
        ),
    )
    dl.set_defaults(func=cmd_download)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
