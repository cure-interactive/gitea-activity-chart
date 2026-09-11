#!/usr/bin/env python3
# =============================================================================
# [Python Script] [CustomTkinter GUI] [Gitea Activity Chart]
# =============================================================================
"""
Fetch Gitea contribution activity and render a trend chart plus contribution heatmap.

Notes:
- First run creates config.json from config-default.json.
- SSH agent/Pageant authentication is preferred; token authentication is optional.
- The app resolves the current user automatically if username is blank.
- Daily activity is gathered from the Gitea activity feeds endpoint and then
  grouped by day, week, or month for charting.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import math
import mmap
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any


def _restart_with_compatible_windows_python() -> bool:
  if os.name != "nt" or os.environ.get("GITEA_ACTIVITY_PYTHON_RESTARTED") == "1":
    return False

  script_path = os.path.abspath(__file__)
  script_dir = os.path.dirname(script_path)
  dependency_probe = "import tkinter, customtkinter, requests"
  creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
  candidates: list[tuple[list[str], list[str]]] = []

  venv_python = os.path.join(script_dir, ".venv", "Scripts", "python.exe")
  venv_pythonw = os.path.join(script_dir, ".venv", "Scripts", "pythonw.exe")
  if os.path.isfile(venv_python):
    launch_executable = venv_pythonw if os.path.isfile(venv_pythonw) else venv_python
    candidates.append(([venv_python], [launch_executable]))

  py_launcher = shutil.which("py.exe") or shutil.which("py")
  if py_launcher:
    pyw_launcher = os.path.join(os.path.dirname(py_launcher), "pyw.exe")
    launch_executable = pyw_launcher if os.path.isfile(pyw_launcher) else py_launcher
    for version in ("3.14", "3.13", "3.12", "3.11", "3.10"):
      candidates.append(([py_launcher, f"-{version}"], [launch_executable, f"-{version}"]))

  for probe_prefix, launch_prefix in candidates:
    try:
      probe = subprocess.run(
        [*probe_prefix, "-c", dependency_probe],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        creationflags=creation_flags,
      )
    except (OSError, subprocess.SubprocessError):
      continue
    if probe.returncode != 0:
      continue
    environment = os.environ.copy()
    environment["GITEA_ACTIVITY_PYTHON_RESTARTED"] = "1"
    subprocess.Popen(
      [*launch_prefix, script_path, *sys.argv[1:]],
      cwd=script_dir,
      env=environment,
      stdin=subprocess.DEVNULL,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
    )
    return True
  return False


def _missing_dependency_exit(package: str, install_command: str, error: Exception) -> None:
  if _restart_with_compatible_windows_python():
    raise SystemExit(0)
  message = "\n".join([
    f"Missing dependency: {package}",
    "",
    "Install:",
    f"  {install_command}",
    "",
    f"Original error: {error}",
  ])
  if os.name == "nt":
    try:
      import ctypes
      ctypes.windll.user32.MessageBoxW(0, message, "Gitea Activity Chart", 0x10)
    except Exception:
      pass
  raise SystemExit(message)


try:
  import customtkinter as ctk
except Exception as e:
  _missing_dependency_exit("customtkinter", "pip install customtkinter", e)

try:
  import requests
except Exception as e:
  _missing_dependency_exit("requests", "pip install requests", e)

try:
  import tkinter as tk
  from tkinter import filedialog, messagebox
except Exception as e:
  _missing_dependency_exit("tkinter", "install Python with Tcl/Tk support", e)


APP_TITLE = "Gitea Activity Chart - Cure Interactive"
APP_USER_MODEL_ID = "CureInteractive.GiteaActivityChart"

PATH_DIR_SCRIPT = os.path.abspath(os.path.dirname(__file__))
PATH_CONFIG_JSON = os.path.join(PATH_DIR_SCRIPT, "config.json")
PATH_CONFIG_DEFAULT_JSON = os.path.join(PATH_DIR_SCRIPT, "config-default.json")

DEFAULT_CONFIG: dict[str, Any] = {
  "window": {
    "width": 1120,
    "height": 760,
  },
  "appearance_mode": "System",
  "color_theme": "blue",
  "gitea": {
    "base_url": "https://git.example.com",
    "api_base_path": "/api/v1",
    "auth_method": "ssh-agent",
    "token": "",
    "token_env": "GITEA_TOKEN",
    "username": "",
    "verify_tls": True,
    "timeout_s": 30,
    "page_limit": 50,
    "user_agent": "gitea-activity-chart/1.0",
  },
  "query": {
    "days_back": 180,
    "group_by": "day",
    "rolling_average_days": 7,
    "only_performed_by": True,
    "include_today": True,
  },
}


def _read_json(path: str) -> dict[str, Any] | None:
  try:
    if not os.path.isfile(path):
      return None
    with open(path, "r", encoding="utf-8") as f:
      data = json.load(f)
    return data if isinstance(data, dict) else None
  except Exception:
    return None


def _write_json_atomic(path: str, data: dict[str, Any]) -> None:
  tmp = path + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
  os.replace(tmp, path)


def _deep_copy_json_dict(data: dict[str, Any]) -> dict[str, Any]:
  return json.loads(json.dumps(data))


def _deep_merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
  out = _deep_copy_json_dict(base)
  for key, value in overlay.items():
    if isinstance(value, dict) and isinstance(out.get(key), dict):
      out[key] = _deep_merge_dict(out[key], value)
    else:
      out[key] = value
  return out


def load_or_create_config() -> dict[str, Any]:
  template = _read_json(PATH_CONFIG_DEFAULT_JSON)
  if not isinstance(template, dict):
    template = _deep_copy_json_dict(DEFAULT_CONFIG)
  user_cfg = _read_json(PATH_CONFIG_JSON)
  if isinstance(user_cfg, dict):
    return _deep_merge_dict(template, user_cfg)
  _write_json_atomic(PATH_CONFIG_JSON, template)
  return _deep_copy_json_dict(template)


def set_windows_app_user_model_id(app_id: str) -> None:
  try:
    if os.name != "nt":
      return
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
  except Exception:
    return


def set_window_icon(root, ico_path: str, png_path: str) -> None:
  ico_abs = os.path.abspath(ico_path) if ico_path else ""
  png_abs = os.path.abspath(png_path) if png_path else ""
  try:
    if ico_abs and os.path.isfile(ico_abs):
      root.iconbitmap(ico_abs)
  except Exception:
    pass
  try:
    if png_abs and os.path.isfile(png_abs):
      img = tk.PhotoImage(file=png_abs)
      root.iconphoto(True, img)
      root._iconphoto_ref = img
  except Exception:
    pass


def _safe_int(value: Any, default: int) -> int:
  try:
    return int(str(value).strip())
  except Exception:
    return default


def _format_number(value: int | float) -> str:
  if isinstance(value, float) and not value.is_integer():
    return f"{value:,.2f}"
  return f"{int(value):,}"


def _iso_date(value: dt.date) -> str:
  return value.isoformat()


def _daterange(start: dt.date, end: dt.date) -> list[dt.date]:
  days = (end - start).days
  return [start + dt.timedelta(days=i) for i in range(days + 1)]


def _week_start(value: dt.date) -> dt.date:
  return value - dt.timedelta(days=value.weekday())


def _month_start(value: dt.date) -> dt.date:
  return value.replace(day=1)


def _roll_average(values: list[int], window_size: int) -> list[float]:
  if window_size <= 1:
    return [float(v) for v in values]
  out: list[float] = []
  running_sum = 0.0
  window: list[int] = []
  for value in values:
    running_sum += value
    window.append(value)
    if len(window) > window_size:
      running_sum -= window.pop(0)
    out.append(running_sum / len(window))
  return out


PAGEANT_MAX_MESSAGE = 8192
PAGEANT_COPYDATA_ID = 0x804E50BA


def _pack_ssh_string(value: bytes) -> bytes:
  return struct.pack(">I", len(value)) + value


def _take_ssh_string(data: bytes, offset: int) -> tuple[bytes, int]:
  length = struct.unpack_from(">I", data, offset)[0]
  start = offset + 4
  return data[start : start + length], start + length


def _pageant_query(payload: bytes) -> bytes:
  if os.name != "nt":
    raise RuntimeError("Pageant authentication is available only on Windows.")
  import ctypes

  class CopyData(ctypes.Structure):
    _fields_ = [("dwData", ctypes.c_size_t), ("cbData", ctypes.c_uint32), ("lpData", ctypes.c_void_p)]

  user32 = ctypes.WinDLL("user32", use_last_error=True)
  kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
  user32.FindWindowW.restype = ctypes.c_void_p
  user32.SendMessageW.restype = ctypes.c_ssize_t
  window = user32.FindWindowW("Pageant", "Pageant")
  if not window:
    raise RuntimeError("Pageant is not running.")
  mapping_name = f"PageantRequest{kernel32.GetCurrentThreadId():08x}"
  request = struct.pack(">I", len(payload)) + payload
  if len(request) > PAGEANT_MAX_MESSAGE:
    raise RuntimeError("Pageant request is too large.")
  with mmap.mmap(-1, PAGEANT_MAX_MESSAGE + 4, tagname=mapping_name, access=mmap.ACCESS_WRITE) as shared:
    shared[: len(request)] = request
    name = ctypes.create_string_buffer(mapping_name.encode("ascii") + b"\0")
    message = CopyData(PAGEANT_COPYDATA_ID, len(name), ctypes.cast(name, ctypes.c_void_p))
    if not user32.SendMessageW(window, 74, 0, ctypes.byref(message)):
      raise RuntimeError("Pageant rejected the request.")
    response_length = struct.unpack(">I", shared[:4])[0]
    return shared[4 : 4 + response_length]


def _pageant_identities() -> list[bytes]:
  response = _pageant_query(b"\x0b")
  if not response or response[0] != 12:
    raise RuntimeError("Unexpected Pageant identity response.")
  count = struct.unpack_from(">I", response, 1)[0]
  offset = 5
  result: list[bytes] = []
  for _ in range(count):
    blob, offset = _take_ssh_string(response, offset)
    _, offset = _take_ssh_string(response, offset)
    result.append(blob)
  return result


def _ppk_public_blob(path: Path) -> bytes:
  encoded: list[str] = []
  remaining: int | None = None
  with path.open("r", encoding="utf-8") as stream:
    for raw_line in stream:
      line = raw_line.rstrip("\r\n")
      if remaining is None:
        if line.startswith("Public-Lines:"):
          remaining = int(line.split(":", 1)[1])
        continue
      encoded.append(line)
      remaining -= 1
      if remaining == 0:
        break
  if remaining is None or remaining != 0:
    raise ValueError("The selected PPK does not contain a complete public-key block.")
  return base64.b64decode("".join(encoded))


def _openssh_public_blob(path: Path) -> bytes:
  public_path = path if path.suffix.lower() == ".pub" else Path(str(path) + ".pub")
  public_path = public_path.expanduser().resolve(strict=True)
  parts = public_path.read_text(encoding="utf-8").strip().split()
  if len(parts) < 2 or not parts[0].startswith(("ssh-", "ecdsa-", "sk-")):
    raise ValueError("The selected OpenSSH public key is invalid.")
  try:
    return base64.b64decode(parts[1], validate=True)
  except Exception as error:
    raise ValueError("The selected OpenSSH public key is invalid.") from error


class PageantSigner:
  def __init__(self, key_path: str = "") -> None:
    wanted_blob = None
    if key_path:
      key = Path(key_path).expanduser().resolve(strict=True)
      if key.suffix.lower() != ".ppk":
        raise ValueError("Select a .ppk file when using Pageant key selection.")
      wanted_blob = _ppk_public_blob(key)
      try:
        loaded = _pageant_identities()
      except RuntimeError as error:
        if str(error) != "Pageant is not running.":
          raise
        loaded = []
      if wanted_blob not in loaded:
        pageant = shutil.which("pageant.exe") or shutil.which("pageant")
        if not pageant:
          raise RuntimeError("Pageant is required to load the selected PuTTY key.")
        subprocess.Popen([pageant, str(key)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
          try:
            if wanted_blob in _pageant_identities():
              break
          except RuntimeError:
            pass
          time.sleep(0.1)
        else:
          raise RuntimeError("Pageant did not make the selected PuTTY key available.")
    identities = _pageant_identities()
    if not identities:
      raise RuntimeError("Pageant has no SSH keys loaded.")
    if wanted_blob is not None and wanted_blob not in identities:
      raise RuntimeError("The selected PuTTY key is not loaded in Pageant.")
    self.public_blob = wanted_blob or identities[0]

  def sign(self, data: bytes) -> bytes:
    payload = b"\x0d" + _pack_ssh_string(self.public_blob) + _pack_ssh_string(data) + struct.pack(">I", 0)
    response = _pageant_query(payload)
    if not response or response[0] != 14:
      raise RuntimeError("Unexpected Pageant signing response.")
    signature_blob, _ = _take_ssh_string(response, 1)
    _, offset = _take_ssh_string(signature_blob, 0)
    signature, _ = _take_ssh_string(signature_blob, offset)
    return signature


class OpenSshAgentSigner:
  def __init__(self, key_path: str = "") -> None:
    try:
      import paramiko
    except Exception as error:
      raise RuntimeError("OpenSSH agent authentication requires the paramiko package.") from error
    self._agent = paramiko.Agent()
    keys = list(self._agent.get_keys())
    if not keys:
      raise RuntimeError("The OpenSSH agent has no SSH keys loaded.")
    wanted_blob = _openssh_public_blob(Path(key_path)) if key_path else None
    matching = [key for key in keys if wanted_blob is None or bytes(key.asbytes()) == wanted_blob]
    if not matching:
      raise RuntimeError("The selected OpenSSH key is not loaded in ssh-agent.")
    self._key = matching[0]
    self.public_blob = bytes(self._key.asbytes())

  def sign(self, data: bytes) -> bytes:
    signature_blob = bytes(self._key.sign_ssh_data(data))
    _, offset = _take_ssh_string(signature_blob, 0)
    signature, _ = _take_ssh_string(signature_blob, offset)
    return signature


class SshSignatureAuth(requests.auth.AuthBase):
  def __init__(self, key_path: str = "") -> None:
    if os.name == "nt" and key_path.lower().endswith(".ppk"):
      self._signer = PageantSigner(key_path)
    elif key_path:
      self._signer = OpenSshAgentSigner(key_path)
    elif os.name == "nt":
      try:
        self._signer = PageantSigner()
      except RuntimeError:
        self._signer = OpenSshAgentSigner()
    else:
      self._signer = OpenSshAgentSigner()
    self._lock = threading.Lock()
    self._last_created: int | None = None

  def __call__(self, request):
    with self._lock:
      current = time.time()
      if self._last_created is not None and int(current) <= self._last_created:
        time.sleep(self._last_created + 1 - current + 0.01)
        current = time.time()
      created = max(int(current), (self._last_created or -1) + 1)
      self._last_created = created
      expires = created + 30
      target = request.path_url
      signing_text = "\n".join([
        f"(request-target): {request.method.lower()} {target}",
        f"(created): {created}",
        f"(expires): {expires}",
      ])
      signature = self._signer.sign(signing_text.encode("utf-8"))
      fingerprint = base64.b64encode(hashlib.sha256(self._signer.public_blob).digest()).decode("ascii").rstrip("=")
      request.headers["Signature"] = (
        f'keyId="SHA256:{fingerprint}",algorithm="hs2019",created={created},expires={expires},'
        f'headers="(request-target) (created) (expires)",signature="{base64.b64encode(signature).decode("ascii")}"'
      )
    return request


class GiteaClient:
  def __init__(
    self,
    *,
    base_url: str,
    api_base_path: str,
    token: str = "",
    ssh_key_path: str = "",
    verify_tls: bool,
    timeout_s: int,
    user_agent: str,
  ) -> None:
    self._base_url = base_url.rstrip("/")
    self._api_base_path = api_base_path.rstrip("/")
    self._token = token
    self._auth = SshSignatureAuth(ssh_key_path) if not token else None
    self._verify_tls = verify_tls
    self._timeout_s = timeout_s
    self._user_agent = user_agent

  def _api_url(self, path: str) -> str:
    return f"{self._base_url}{self._api_base_path}/{path.lstrip('/')}"

  def _headers(self) -> dict[str, str]:
    headers = {
      "Accept": "application/json",
      "User-Agent": self._user_agent,
    }
    if self._token:
      headers["Authorization"] = f"token {self._token}"
    return headers

  def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
    def send(request_path: str, request_params: dict[str, Any] | None = None):
      return requests.get(
        self._api_url(request_path),
        headers=self._headers(),
        auth=self._auth,
        params=request_params,
        timeout=self._timeout_s,
        verify=self._verify_tls,
      )

    response = send(path, params)
    recoverable = self._auth is not None and path.rstrip("/") != "/user" and response.status_code in {401, 403}
    if recoverable:
      identity_response = send("/user")
      if identity_response.status_code < 400:
        response = send(path, params)
    if response.status_code >= 400:
      raise RuntimeError(f"Gitea API failed: {response.status_code} {response.text}")
    return response.json()

  def get_current_user(self) -> dict[str, Any]:
    data = self._get_json("/user")
    if not isinstance(data, dict):
      raise RuntimeError("Unexpected /user response payload.")
    return data

  def list_visible_users(self, *, page_limit: int = 50) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    seen: set[str] = set()
    page = 1
    limit = max(1, min(100, page_limit))
    while True:
      payload = self._get_json("/users/search", params={"q": "", "page": page, "limit": limit})
      if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError("Unexpected user search response payload.")
      batch = payload["data"]
      for value in batch:
        if not isinstance(value, dict):
          continue
        login = str(value.get("login") or value.get("username") or "").strip()
        identity = login.casefold()
        if login and identity not in seen:
          seen.add(identity)
          users.append(value)
      if len(batch) < limit:
        break
      page += 1
    return users

  def count_user_activity_for_day(
    self,
    *,
    username: str,
    day: dt.date,
    page_limit: int,
    only_performed_by: bool,
  ) -> int:
    page = 1
    total = 0
    params_base = {
      "date": _iso_date(day),
      "limit": max(1, page_limit),
      "only-performed-by": "true" if only_performed_by else "false",
    }
    while True:
      params = dict(params_base)
      params["page"] = page
      data = self._get_json(f"/users/{username}/activities/feeds", params=params)
      if not isinstance(data, list):
        raise RuntimeError("Unexpected activity feed response payload.")
      batch_len = len(data)
      total += batch_len
      if batch_len < page_limit:
        break
      page += 1
    return total


class GiteaActivityChartApp(ctk.CTk):
  def __init__(self) -> None:
    super().__init__()

    self.config_data = load_or_create_config()

    ctk.set_appearance_mode(str(self.config_data.get("appearance_mode", "System")))
    ctk.set_default_color_theme(str(self.config_data.get("color_theme", "blue")))

    w = int(self.config_data.get("window", {}).get("width", 1180))
    h = int(self.config_data.get("window", {}).get("height", 900))

    self.title(APP_TITLE)
    self.geometry(f"{w}x{h}")
    self.minsize(960, 650)

    set_window_icon(
      self,
      os.path.join(PATH_DIR_SCRIPT, "icon.ico"),
      os.path.join(PATH_DIR_SCRIPT, "icon.png"),
    )

    self._worker_thread: threading.Thread | None = None
    self._busy = False
    self._last_results: list[tuple[dt.date, int]] = []
    self._last_grouped: OrderedDict[str, int] = OrderedDict()
    self._last_username = ""
    self._heatmap_cells: list[tuple[float, float, float, float, dt.date, int, int]] = []
    self._heatmap_hovered_item: int | None = None
    self._heatmap_layout_snapshot: dict[str, int] = {}
    self._visible_user_logins: dict[str, str] = {}
    self._visible_user_options: list[str] = []
    self._activity_cache: dict[tuple[str, str, str, str, bool], list[tuple[dt.date, int]]] = {}
    self._log_lines: list[str] = []
    self._log_window = None
    self._log_text = None

    gitea_cfg = self.config_data.get("gitea", {})
    query_cfg = self.config_data.get("query", {})
    if not isinstance(gitea_cfg, dict):
      gitea_cfg = {}
    if not isinstance(query_cfg, dict):
      query_cfg = {}

    self.var_base_url = tk.StringVar(value=str(gitea_cfg.get("base_url", "https://git.example.com")))
    self.var_api_base_path = tk.StringVar(value=str(gitea_cfg.get("api_base_path", "/api/v1")))
    self.var_auth_method = tk.StringVar(value=str(gitea_cfg.get("auth_method", "ssh-agent")))
    self.var_ssh_key_path = tk.StringVar(value="")
    self.var_token = tk.StringVar(value=str(gitea_cfg.get("token", "")))
    self.var_token_env = tk.StringVar(value=str(gitea_cfg.get("token_env", "GITEA_TOKEN")))
    self.var_username = tk.StringVar(value=str(gitea_cfg.get("username", "")))
    self.var_user_selection = tk.StringVar(value=self.var_username.get())
    self.var_verify_tls = tk.BooleanVar(value=bool(gitea_cfg.get("verify_tls", True)))
    self.var_timeout_s = tk.StringVar(value=str(gitea_cfg.get("timeout_s", 30)))
    self.var_page_limit = tk.StringVar(value=str(gitea_cfg.get("page_limit", 50)))
    self.var_user_agent = tk.StringVar(value=str(gitea_cfg.get("user_agent", "gitea-activity-chart/1.0")))
    self.var_days_back = tk.StringVar(value=str(query_cfg.get("days_back", 180)))
    self.var_group_by = tk.StringVar(value=str(query_cfg.get("group_by", "day")))
    self.var_rolling_average_days = tk.StringVar(value=str(query_cfg.get("rolling_average_days", 7)))
    self.var_only_performed_by = tk.BooleanVar(value=bool(query_cfg.get("only_performed_by", True)))
    self.var_include_today = tk.BooleanVar(value=bool(query_cfg.get("include_today", True)))

    self._build_ui()
    self.protocol("WM_DELETE_WINDOW", self._on_close)
    self._draw_empty_states()
    self.after(350, lambda: self._on_refresh_users(show_errors=False))

  def _build_ui(self) -> None:
    self.grid_columnconfigure(0, weight=1)
    self.grid_rowconfigure(0, weight=1)

    self.tabview = ctk.CTkTabview(self)
    self.tabview.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    activity_tab = self.tabview.add("Activity")
    config_tab = self.tabview.add("Configuration")
    self.tabview.set("Activity")
    activity_tab.grid_columnconfigure(0, weight=1)
    activity_tab.grid_rowconfigure(1, weight=1)
    config_tab.grid_columnconfigure(0, weight=1)

    top = ctk.CTkFrame(config_tab)
    top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
    top.grid_columnconfigure(1, weight=3)
    top.grid_columnconfigure(3, weight=2)

    ctk.CTkLabel(top, text="Connection", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 2))
    ctk.CTkLabel(top, text="Base URL").grid(row=1, column=0, sticky="w", padx=(12, 6), pady=6)
    ctk.CTkEntry(top, textvariable=self.var_base_url).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=6)
    ctk.CTkLabel(top, text="API Path").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=6)
    ctk.CTkEntry(top, textvariable=self.var_api_base_path).grid(row=1, column=3, sticky="ew", padx=(0, 12), pady=6)

    ctk.CTkLabel(top, text="Request timeout").grid(row=2, column=0, sticky="w", padx=(12, 6), pady=6)
    request_row = ctk.CTkFrame(top, fg_color="transparent")
    request_row.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=6)
    request_row.grid_columnconfigure(0, weight=1)
    ctk.CTkEntry(request_row, textvariable=self.var_timeout_s, width=72).grid(row=0, column=0, sticky="ew")
    ctk.CTkLabel(request_row, text="sec timeout").grid(row=0, column=1, padx=(6, 12))
    ctk.CTkCheckBox(request_row, text="Verify TLS", variable=self.var_verify_tls).grid(row=0, column=2)

    ctk.CTkLabel(top, text="Authentication", font=ctk.CTkFont(size=16, weight="bold")).grid(row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(12, 2))
    ctk.CTkLabel(top, text="Method").grid(row=4, column=0, sticky="w", padx=(12, 6), pady=6)
    ctk.CTkOptionMenu(top, variable=self.var_auth_method, values=["ssh-agent", "token"], command=lambda _value: self._update_auth_controls()).grid(row=4, column=1, sticky="ew", padx=(0, 12), pady=6)
    self.lbl_auth_hint = ctk.CTkLabel(top, text="", anchor="w")
    self.lbl_auth_hint.grid(row=4, column=2, columnspan=2, sticky="ew", padx=(0, 12), pady=6)

    ctk.CTkLabel(top, text="SSH / PuTTY key").grid(row=5, column=0, sticky="w", padx=(12, 6), pady=(6, 10))
    key_row = ctk.CTkFrame(top, fg_color="transparent")
    key_row.grid(row=5, column=1, sticky="ew", padx=(0, 12), pady=(6, 10))
    key_row.grid_columnconfigure(0, weight=1)
    self.entry_ssh_key = ctk.CTkEntry(key_row, textvariable=self.var_ssh_key_path, placeholder_text="Optional key selector; otherwise use an agent key")
    self.entry_ssh_key.grid(row=0, column=0, sticky="ew")
    self.btn_browse_key = ctk.CTkButton(key_row, text="Browse", width=72, command=self._browse_ssh_key)
    self.btn_browse_key.grid(row=0, column=1, padx=(6, 0))
    ctk.CTkLabel(top, text="Token / env").grid(row=5, column=2, sticky="w", padx=(0, 6), pady=(6, 10))
    token_row = ctk.CTkFrame(top, fg_color="transparent")
    token_row.grid(row=5, column=3, sticky="ew", padx=(0, 12), pady=(6, 10))
    token_row.grid_columnconfigure(0, weight=2)
    token_row.grid_columnconfigure(1, weight=1)
    self.entry_token = ctk.CTkEntry(token_row, textvariable=self.var_token, show="*", placeholder_text="Token")
    self.entry_token.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    self.entry_token_env = ctk.CTkEntry(token_row, textvariable=self.var_token_env, placeholder_text="Environment variable")
    self.entry_token_env.grid(row=0, column=1, sticky="ew")
    ctk.CTkButton(top, text="Save Configuration", command=self._on_save).grid(row=6, column=3, sticky="e", padx=12, pady=(4, 12))
    self._update_auth_controls()

    options = ctk.CTkFrame(activity_tab)
    options.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
    for col in range(8):
      options.grid_columnconfigure(col, weight=1)

    ctk.CTkLabel(options, text="Visible user").grid(row=0, column=0, sticky="w", padx=(10, 6), pady=8)
    user_row = ctk.CTkFrame(options, fg_color="transparent")
    user_row.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(0, 10), pady=8)
    user_row.grid_columnconfigure(0, weight=1)
    initial_users = [self.var_username.get()] if self.var_username.get().strip() else [""]
    self.user_combo = ctk.CTkComboBox(user_row, variable=self.var_user_selection, values=initial_users, command=self._on_user_selected)
    self.user_combo.grid(row=0, column=0, sticky="ew")
    self.user_combo.bind("<KeyRelease>", self._on_user_search_typed)
    self.btn_refresh_users = ctk.CTkButton(user_row, text="Refresh", width=78, command=self._on_refresh_users)
    self.btn_refresh_users.grid(row=0, column=1, padx=(6, 0))

    ctk.CTkLabel(options, text="Days Back").grid(row=1, column=0, sticky="w", padx=(10, 6), pady=8)
    ctk.CTkEntry(options, textvariable=self.var_days_back).grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=8)
    ctk.CTkLabel(options, text="Group By").grid(row=1, column=2, sticky="w", padx=(10, 6), pady=8)
    ctk.CTkOptionMenu(options, variable=self.var_group_by, values=["day", "week", "month"], command=lambda _value: self._redraw_from_last_results()).grid(row=1, column=3, sticky="ew", padx=(0, 10), pady=8)
    ctk.CTkLabel(options, text="Rolling Avg").grid(row=1, column=4, sticky="w", padx=(10, 6), pady=8)
    ctk.CTkEntry(options, textvariable=self.var_rolling_average_days).grid(row=1, column=5, sticky="ew", padx=(0, 10), pady=8)
    ctk.CTkLabel(options, text="Page Limit").grid(row=1, column=6, sticky="w", padx=(10, 6), pady=8)
    ctk.CTkEntry(options, textvariable=self.var_page_limit).grid(row=1, column=7, sticky="ew", padx=(0, 10), pady=8)

    ctk.CTkCheckBox(options, text="Only performed by this user", variable=self.var_only_performed_by).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))
    ctk.CTkCheckBox(options, text="Include today", variable=self.var_include_today).grid(row=2, column=2, columnspan=2, sticky="w", padx=10, pady=(0, 10))

    summary = ctk.CTkFrame(activity_tab)
    summary.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
    summary.grid_columnconfigure(0, weight=2)
    summary.grid_columnconfigure(1, weight=1)
    summary.grid_rowconfigure(0, weight=1)

    chart_panel = ctk.CTkFrame(summary)
    chart_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)
    chart_panel.grid_columnconfigure(0, weight=1)
    chart_panel.grid_rowconfigure(2, weight=1)

    chart_title_row = ctk.CTkFrame(chart_panel, fg_color="transparent")
    chart_title_row.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
    ctk.CTkLabel(chart_title_row, text="Trend Chart", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w")
    self.lbl_chart_subtitle = ctk.CTkLabel(chart_panel, text="No data loaded", anchor="w")
    self.lbl_chart_subtitle.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))

    self.canvas_chart = tk.Canvas(chart_panel, highlightthickness=0, bg="#0f172a")
    self.canvas_chart.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
    self.canvas_chart.bind("<Configure>", lambda _e: self._draw_line_chart())

    side = ctk.CTkFrame(summary)
    side.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=0)
    side.grid_columnconfigure(0, weight=1)
    side.grid_rowconfigure(1, weight=1)

    metrics = ctk.CTkFrame(side)
    metrics.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 8))
    for column in range(4):
      metrics.grid_columnconfigure(column, weight=1)

    self.lbl_total = self._metric(metrics, 0, 0, "Total", "0")
    self.lbl_peak = self._metric(metrics, 0, 1, "Peak", "0")
    self.lbl_avg = self._metric(metrics, 0, 2, "Average", "0")
    self.lbl_streak = self._metric(metrics, 0, 3, "Best Streak", "0")

    heatmap_frame = ctk.CTkFrame(side)
    heatmap_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
    heatmap_frame.grid_columnconfigure(0, weight=1)
    heatmap_frame.grid_rowconfigure(2, weight=1)
    ctk.CTkLabel(heatmap_frame, text="Contribution Heatmap", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
    self.lbl_heatmap_detail = ctk.CTkLabel(heatmap_frame, text="No data loaded", anchor="w", text_color="#94a3b8")
    self.lbl_heatmap_detail.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
    self.canvas_heatmap = tk.Canvas(heatmap_frame, highlightthickness=0, bg="#0f172a")
    self.canvas_heatmap.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
    self.canvas_heatmap.bind("<Configure>", lambda _e: self._draw_heatmap())
    self.canvas_heatmap.bind("<Motion>", self._on_heatmap_motion)
    self.canvas_heatmap.bind("<Leave>", self._on_heatmap_leave)

    bottom = ctk.CTkFrame(activity_tab)
    bottom.grid(row=2, column=0, sticky="ew", padx=8, pady=(8, 8))
    bottom.grid_columnconfigure(0, weight=1)
    bottom.grid_rowconfigure(1, weight=1)

    actions = ctk.CTkFrame(bottom)
    actions.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 8))
    actions.grid_columnconfigure(6, weight=1)

    self.btn_fetch = ctk.CTkButton(actions, text="Fetch Activity", command=self._on_fetch_activity)
    self.btn_fetch.grid(row=0, column=0, padx=(0, 8), pady=8)
    ctk.CTkButton(actions, text="Export CSV", command=self._on_export_csv).grid(row=0, column=1, padx=(0, 8), pady=8)
    ctk.CTkButton(actions, text="Clear Data", command=self._clear_results).grid(row=0, column=2, padx=(0, 8), pady=8)
    self.btn_toggle_log = ctk.CTkButton(actions, text="Open Log", width=90, command=self._toggle_log)
    self.btn_toggle_log.grid(row=0, column=3, padx=(0, 8), pady=8)
    self.progress = ctk.CTkProgressBar(actions)
    self.progress.grid(row=0, column=6, sticky="ew", padx=(10, 10), pady=8)
    self.progress.set(0)
    self.lbl_status = ctk.CTkLabel(actions, text="Idle")
    self.lbl_status.grid(row=0, column=8, sticky="e", padx=(8, 0), pady=8)

  def _metric(self, parent, row: int, col: int, title: str, value: str):
    card = ctk.CTkFrame(parent)
    card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
    card.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(card, text=title).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
    lbl = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold"))
    lbl.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))
    return lbl

  def _log(self, msg: str) -> None:
    line = str(msg).rstrip()
    if not line:
      return
    self._log_lines.append(line)
    self._log_lines = self._log_lines[-1000:]
    if self._log_text is not None:
      self._log_text.configure(state="normal")
      self._log_text.insert("end", line + "\n")
      self._log_text.see("end")
      self._log_text.configure(state="disabled")

  def _set_status(self, text: str, progress: float | None = None) -> None:
    self.lbl_status.configure(text=text)
    if progress is not None:
      self.progress.set(max(0.0, min(1.0, progress)))

  def _toggle_log(self) -> None:
    if self._log_window is not None and self._log_window.winfo_exists():
      self._log_window.focus()
      return
    window = ctk.CTkToplevel(self)
    window.title(f"Activity Log — {APP_TITLE}")
    window.geometry("820x360")
    window.minsize(600, 240)
    window.grid_columnconfigure(0, weight=1)
    window.grid_rowconfigure(0, weight=1)
    text = ctk.CTkTextbox(window)
    text.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
    text.insert("1.0", "\n".join(self._log_lines) + ("\n" if self._log_lines else ""))
    text.configure(state="disabled")
    self._log_window = window
    self._log_text = text

    def close_log() -> None:
      window.destroy()
      self._log_window = None
      self._log_text = None

    window.protocol("WM_DELETE_WINDOW", close_log)
    window.focus()

  def _collect_config_from_ui(self) -> dict[str, Any]:
    cfg = _deep_copy_json_dict(DEFAULT_CONFIG)
    geometry_match = re.match(r"^(\d+)x(\d+)", self.geometry())
    logical_width = int(geometry_match.group(1)) if geometry_match else int(DEFAULT_CONFIG["window"]["width"])
    logical_height = int(geometry_match.group(2)) if geometry_match else int(DEFAULT_CONFIG["window"]["height"])
    cfg["window"]["width"] = max(logical_width, 960)
    cfg["window"]["height"] = max(logical_height, 650)
    cfg["appearance_mode"] = str(self.config_data.get("appearance_mode", "System"))
    cfg["color_theme"] = str(self.config_data.get("color_theme", "blue"))
    cfg["gitea"]["base_url"] = self.var_base_url.get().strip()
    cfg["gitea"]["api_base_path"] = self.var_api_base_path.get().strip() or "/api/v1"
    cfg["gitea"]["auth_method"] = self.var_auth_method.get().strip() or "ssh-agent"
    cfg["gitea"]["token"] = self.var_token.get().strip()
    cfg["gitea"]["token_env"] = self.var_token_env.get().strip() or "GITEA_TOKEN"
    cfg["gitea"]["username"] = self.var_username.get().strip()
    cfg["gitea"]["verify_tls"] = bool(self.var_verify_tls.get())
    cfg["gitea"]["timeout_s"] = max(1, _safe_int(self.var_timeout_s.get(), 30))
    cfg["gitea"]["page_limit"] = max(1, min(100, _safe_int(self.var_page_limit.get(), 50)))
    cfg["gitea"]["user_agent"] = self.var_user_agent.get().strip() or "gitea-activity-chart/1.0"
    cfg["query"]["days_back"] = max(1, min(3660, _safe_int(self.var_days_back.get(), 180)))
    cfg["query"]["group_by"] = self.var_group_by.get().strip() or "day"
    cfg["query"]["rolling_average_days"] = max(1, min(365, _safe_int(self.var_rolling_average_days.get(), 7)))
    cfg["query"]["only_performed_by"] = bool(self.var_only_performed_by.get())
    cfg["query"]["include_today"] = bool(self.var_include_today.get())
    return cfg

  def _browse_ssh_key(self) -> None:
    path = filedialog.askopenfilename(
      title="Select loaded SSH key",
      filetypes=[("SSH key", "*.ppk *.pub"), ("PuTTY private key", "*.ppk"), ("OpenSSH public key", "*.pub"), ("All files", "*.*")],
    )
    if path:
      self.var_ssh_key_path.set(path)
      self._log("Selected an SSH key for this session. Its path will not be saved.")

  def _update_auth_controls(self) -> None:
    use_ssh = self.var_auth_method.get().strip() != "token"
    ssh_state = "normal" if use_ssh else "disabled"
    token_state = "disabled" if use_ssh else "normal"
    self.entry_ssh_key.configure(state=ssh_state)
    self.btn_browse_key.configure(state=ssh_state)
    self.entry_token.configure(state=token_state)
    self.entry_token_env.configure(state=token_state)
    hint = "Pageant / SSH agent (recommended)" if use_ssh else "Token fallback"
    self.lbl_auth_hint.configure(text=hint)

  def _save_config(self) -> None:
    self.config_data = self._collect_config_from_ui()
    _write_json_atomic(PATH_CONFIG_JSON, self.config_data)

  def _on_save(self) -> None:
    try:
      selected = self._selected_username()
      if selected:
        self.var_username.set(selected)
      self._save_config()
      self._log(f"Saved config: {PATH_CONFIG_JSON}")
    except Exception as e:
      messagebox.showerror(APP_TITLE, f"Failed to save config:\n{e}")

  def _resolve_token(self) -> str:
    inline = self.var_token.get().strip()
    if inline:
      return inline
    token_env = self.var_token_env.get().strip()
    if token_env:
      env_value = os.environ.get(token_env, "").strip()
      if env_value:
        return env_value
    return ""

  def _build_client(self) -> GiteaClient:
    auth_method = self.var_auth_method.get().strip() or "ssh-agent"
    if auth_method not in {"ssh-agent", "token"}:
      raise ValueError("Authentication must be ssh-agent or token.")
    token = self._resolve_token() if auth_method == "token" else ""
    if auth_method == "token" and not token:
      raise ValueError("Provide a Gitea token or set the configured token environment variable.")
    base_url = self.var_base_url.get().strip()
    if not base_url:
      raise ValueError("Base URL is required.")
    return GiteaClient(
      base_url=base_url,
      api_base_path=self.var_api_base_path.get().strip() or "/api/v1",
      token=token,
      ssh_key_path=self.var_ssh_key_path.get().strip(),
      verify_tls=bool(self.var_verify_tls.get()),
      timeout_s=max(1, _safe_int(self.var_timeout_s.get(), 30)),
      user_agent=self.var_user_agent.get().strip() or "gitea-activity-chart/1.0",
    )

  def _set_busy(self, busy: bool) -> None:
    self._busy = busy
    self.btn_fetch.configure(state="disabled" if busy else "normal")
    self.btn_refresh_users.configure(state="disabled" if busy else "normal")

  def _selected_username(self) -> str:
    value = self.var_user_selection.get().strip()
    if value in self._visible_user_logins:
      return self._visible_user_logins[value]
    match = re.search(r"\(@([^)]+)\)\s*$", value)
    if match:
      return match.group(1).strip()
    return value.removeprefix("@").strip()

  def _activity_cache_key(self, username: str) -> tuple[str, str, str, str, bool]:
    days_back = max(1, min(3660, _safe_int(self.var_days_back.get(), 180)))
    include_today = bool(self.var_include_today.get())
    end_date = dt.date.today() if include_today else (dt.date.today() - dt.timedelta(days=1))
    start_date = end_date - dt.timedelta(days=days_back - 1)
    return (
      self.var_base_url.get().strip().rstrip("/").casefold(),
      username.casefold(),
      start_date.isoformat(),
      end_date.isoformat(),
      bool(self.var_only_performed_by.get()),
    )

  def _on_user_selected(self, _display_value: str) -> None:
    username = self._selected_username()
    if not username:
      return
    self.var_username.set(username)
    cache_key = self._activity_cache_key(username)
    cached = self._activity_cache.get(cache_key)
    if cached is not None:
      self._last_username = username
      self._last_results = list(cached)
      self._redraw_from_last_results()
      self._set_status(f"Cached activity: @{username}", 1.0)
      self._log(f"Loaded {len(cached)} cached daily rows for {username}.")
      return
    self._last_results = []
    self._last_grouped = OrderedDict()
    self._last_username = username
    self._draw_empty_states()
    self._set_status(f"Ready to fetch @{username}", 0)

  def _on_user_search_typed(self, _event=None) -> None:
    query = self.var_user_selection.get().strip().casefold()
    if not query:
      matches = self._visible_user_options
    else:
      matches = [
        display for display in self._visible_user_options
        if query in display.casefold() or query in self._visible_user_logins.get(display, "").casefold()
      ]
    self.user_combo.configure(values=matches or self._visible_user_options)

  @staticmethod
  def _user_display(user: dict[str, Any], current_login: str) -> tuple[str, str]:
    login = str(user.get("login") or user.get("username") or "").strip()
    full_name = str(user.get("full_name") or "").strip()
    if login.casefold() == current_login.casefold():
      return f"Me (@{login})", login
    return (f"{full_name} (@{login})" if full_name else f"@{login}"), login

  def _on_refresh_users(self, _event=None, *, show_errors: bool = True) -> None:
    if self._busy:
      return
    try:
      client = self._build_client()
      self._set_busy(True)
      self._set_status("Loading visible users...", 0.05)
    except Exception as e:
      if show_errors:
        messagebox.showerror(APP_TITLE, str(e))
      else:
        self._log(f"Visible-user discovery skipped: {e}")
      return

    def worker() -> None:
      try:
        user = client.get_current_user()
        current_login = str(user.get("login") or user.get("username") or "").strip()
        if not current_login:
          raise RuntimeError("Unable to resolve username from Gitea /user response.")
        users = client.list_visible_users(page_limit=max(1, min(100, _safe_int(self.var_page_limit.get(), 50))))
        self.after(0, lambda: self._on_users_loaded(current_login, users))
      except Exception as e:
        self.after(0, lambda: self._on_user_refresh_failed(str(e), show_errors))

    threading.Thread(target=worker, daemon=True).start()

  def _on_users_loaded(self, current_login: str, users: list[dict[str, Any]]) -> None:
    ordered = sorted(
      users,
      key=lambda user: (
        str(user.get("login") or user.get("username") or "").casefold() != current_login.casefold(),
        str(user.get("full_name") or user.get("login") or user.get("username") or "").casefold(),
      ),
    )
    options = [self._user_display(user, current_login) for user in ordered]
    if current_login.casefold() not in {login.casefold() for _, login in options}:
      options.insert(0, (f"Me (@{current_login})", current_login))
    self._visible_user_logins = {display: login for display, login in options}
    self._visible_user_options = [display for display, _ in options]
    self.user_combo.configure(values=self._visible_user_options)
    selected_login = self.var_username.get().strip() or current_login
    selected_display = next((display for display, login in options if login.casefold() == selected_login.casefold()), selected_login)
    self.var_user_selection.set(selected_display)
    self.var_username.set(selected_login)
    self._set_busy(False)
    self._set_status(f"{len(options)} visible users", 0)
    self._log(f"Loaded {len(options)} visible users; current user is {current_login}.")

  def _on_user_refresh_failed(self, error_text: str, show_errors: bool) -> None:
    self._set_busy(False)
    self._set_status("User list unavailable", 0)
    self._log(f"Visible-user discovery failed: {error_text}")
    if show_errors:
      messagebox.showerror(APP_TITLE, error_text)

  def _on_fetch_activity(self) -> None:
    if self._busy:
      return
    try:
      username = self._selected_username()
      if not username:
        client = self._build_client()
        user = client.get_current_user()
        username = str(user.get("login") or user.get("username") or "").strip()
        if not username:
          raise RuntimeError("Username is blank and could not be resolved from /user.")
      self.var_username.set(username)
      cfg = self._collect_config_from_ui()
      days_back = int(cfg["query"]["days_back"])
      include_today = bool(cfg["query"]["include_today"])
      end_date = dt.date.today() if include_today else (dt.date.today() - dt.timedelta(days=1))
      start_date = end_date - dt.timedelta(days=days_back - 1)
      cache_key = self._activity_cache_key(username)
      self._save_config()
      cached = self._activity_cache.get(cache_key)
      if cached is not None:
        self._on_fetch_complete(username, list(cached), cache_key, from_cache=True)
        return
      client = self._build_client()
    except Exception as e:
      messagebox.showerror(APP_TITLE, str(e))
      return

    only_performed_by = bool(cfg["query"]["only_performed_by"])
    page_limit = int(cfg["gitea"]["page_limit"])

    self._set_busy(True)
    self._set_status("Fetching activity...", 0)
    self._log(f"Fetching {days_back} day(s) for {username} from {start_date.isoformat()} to {end_date.isoformat()}")

    def worker() -> None:
      try:
        points: list[tuple[dt.date, int]] = []
        days = _daterange(start_date, end_date)
        total_days = len(days)
        for idx, day in enumerate(days, start=1):
          count = client.count_user_activity_for_day(
            username=username,
            day=day,
            page_limit=page_limit,
            only_performed_by=only_performed_by,
          )
          points.append((day, count))
          pct = idx / total_days if total_days else 1.0
          self.after(0, lambda idx=idx, total_days=total_days, day=day, count=count, pct=pct: self._on_fetch_progress(idx, total_days, day, count, pct))
        self.after(0, lambda: self._on_fetch_complete(username, points, cache_key))
      except Exception as e:
        self.after(0, lambda: self._on_fetch_failed(str(e)))

    self._worker_thread = threading.Thread(target=worker, daemon=True)
    self._worker_thread.start()

  def _on_fetch_progress(self, idx: int, total_days: int, day: dt.date, count: int, pct: float) -> None:
    self._set_status(f"{idx}/{total_days} {day.isoformat()} = {count}", pct)

  def _on_fetch_complete(
    self,
    username: str,
    points: list[tuple[dt.date, int]],
    cache_key: tuple[str, str, str, str, bool],
    *,
    from_cache: bool = False,
  ) -> None:
    self._set_busy(False)
    self._set_status("Idle", 1.0 if points else 0.0)
    self._last_username = username
    self._last_results = list(points)
    self._activity_cache[cache_key] = list(points)
    action = "Loaded" if from_cache else "Fetched"
    suffix = " from memory" if from_cache else ""
    self._log(f"{action} {len(points)} daily rows for {username}{suffix}.")
    self._redraw_from_last_results()

  def _on_fetch_failed(self, error_text: str) -> None:
    self._set_busy(False)
    self._set_status("Idle", 0)
    self._log(f"Fetch failed: {error_text}")
    messagebox.showerror(APP_TITLE, error_text)

  def _clear_results(self) -> None:
    self._last_results = []
    self._last_grouped = OrderedDict()
    self._last_username = ""
    self._draw_empty_states()
    self._log("Cleared in-memory results.")
    self._set_status("Idle", 0)

  def _draw_empty_states(self) -> None:
    self.lbl_total.configure(text="0")
    self.lbl_peak.configure(text="0")
    self.lbl_avg.configure(text="0")
    self.lbl_streak.configure(text="0")
    self.lbl_chart_subtitle.configure(text="No data loaded")
    self.lbl_heatmap_detail.configure(text="No data loaded")
    self._heatmap_cells = []
    self._heatmap_hovered_item = None
    self._heatmap_layout_snapshot = {}
    self.canvas_chart.delete("all")
    self.canvas_heatmap.delete("all")
    self.canvas_chart.create_text(120, 60, text="Fetch activity to render the chart.", fill="#cbd5e1", anchor="w", font=("Segoe UI", 14, "bold"))
    self.canvas_heatmap.create_text(120, 60, text="Heatmap will appear after loading data.", fill="#cbd5e1", anchor="w", font=("Segoe UI", 14, "bold"))

  def _group_daily_counts(self, points: list[tuple[dt.date, int]]) -> OrderedDict[str, int]:
    mode = self.var_group_by.get().strip() or "day"
    grouped: OrderedDict[str, int] = OrderedDict()
    if mode == "day":
      for day, count in points:
        grouped[day.isoformat()] = grouped.get(day.isoformat(), 0) + count
      return grouped
    if mode == "week":
      for day, count in points:
        start = _week_start(day)
        key = f"{start.isoformat()} week"
        grouped[key] = grouped.get(key, 0) + count
      return grouped
    for day, count in points:
      start = _month_start(day)
      key = start.strftime("%Y-%m")
      grouped[key] = grouped.get(key, 0) + count
    return grouped

  def _redraw_from_last_results(self) -> None:
    if not self._last_results:
      self._draw_empty_states()
      return

    grouped = self._group_daily_counts(self._last_results)
    self._last_grouped = grouped
    total = sum(v for _, v in self._last_results)
    peak = max(v for _, v in self._last_results)
    avg = total / len(self._last_results) if self._last_results else 0
    best_streak = 0
    streak = 0
    for _day, count in self._last_results:
      if count > 0:
        streak += 1
        best_streak = max(best_streak, streak)
      else:
        streak = 0

    self.lbl_total.configure(text=_format_number(total))
    self.lbl_peak.configure(text=_format_number(peak))
    self.lbl_avg.configure(text=_format_number(avg))
    self.lbl_streak.configure(text=_format_number(best_streak))
    if self._last_results:
      start = self._last_results[0][0].isoformat()
      end = self._last_results[-1][0].isoformat()
      self.lbl_chart_subtitle.configure(text=f"{self._last_username or 'user'} | {start} to {end} | grouped by {self.var_group_by.get()}")
      self.lbl_heatmap_detail.configure(text=self._heatmap_summary_text())

    # Metric text can change the grid's requested width. Resolve that geometry
    # before using canvas dimensions so an old, wider plot is never left behind.
    self.update_idletasks()
    self._draw_line_chart()
    self._draw_heatmap()

  def _draw_line_chart(self) -> None:
    canvas = self.canvas_chart
    canvas.delete("all")
    w = max(320, canvas.winfo_width())
    h = max(220, canvas.winfo_height())
    canvas.configure(bg="#0f172a")

    if not self._last_grouped:
      canvas.create_text(120, 60, text="Fetch activity to render the chart.", fill="#cbd5e1", anchor="w", font=("Segoe UI", 14, "bold"))
      return

    left = 60
    top = 20
    right = w - 20
    bottom = h - 50
    chart_w = max(40, right - left)
    chart_h = max(40, bottom - top)

    labels = list(self._last_grouped.keys())
    values = list(self._last_grouped.values())
    rolling = _roll_average([int(v) for v in values], max(1, _safe_int(self.var_rolling_average_days.get(), 7)))
    max_value = max(max(values), max(rolling) if rolling else 0, 1)

    canvas.create_rectangle(0, 0, w, h, fill="#0f172a", outline="")
    for idx in range(5):
      y = top + (chart_h * idx / 4)
      value = max_value - ((max_value * idx) / 4)
      canvas.create_line(left, y, right, y, fill="#1e293b", width=1)
      canvas.create_text(left - 10, y, text=_format_number(value), fill="#94a3b8", anchor="e", font=("Segoe UI", 9))

    def to_point(index: int, value: float, count: int) -> tuple[float, float]:
      x = left if count <= 1 else left + (chart_w * index / (count - 1))
      y = bottom - ((value / max_value) * chart_h)
      return x, y

    count = len(values)
    if count == 1:
      x, y = to_point(0, values[0], 1)
      canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#38bdf8", outline="")
    else:
      line_points: list[float] = []
      avg_points: list[float] = []
      for idx, value in enumerate(values):
        x, y = to_point(idx, value, count)
        line_points.extend([x, y])
        avg_x, avg_y = to_point(idx, rolling[idx], count)
        avg_points.extend([avg_x, avg_y])
        canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#38bdf8", outline="")
      canvas.create_line(*line_points, fill="#38bdf8", width=3, smooth=True)
      canvas.create_line(*avg_points, fill="#f59e0b", width=2, smooth=True, dash=(6, 4))

    ticks = min(6, len(labels))
    for tick_index in range(ticks):
      source_index = 0 if ticks == 1 else round((len(labels) - 1) * tick_index / (ticks - 1))
      x, _ = to_point(source_index, 0, max(1, len(labels)))
      canvas.create_text(x, bottom + 16, text=labels[source_index], fill="#94a3b8", anchor="n", font=("Segoe UI", 8))

    canvas.create_line(left, top, left, bottom, fill="#475569", width=2)
    canvas.create_line(left, bottom, right, bottom, fill="#475569", width=2)
    canvas.create_text(right, top - 2, text=f"Rolling avg: {max(1, _safe_int(self.var_rolling_average_days.get(), 7))}", fill="#fbbf24", anchor="ne", font=("Segoe UI", 9, "bold"))

  def _draw_heatmap(self) -> None:
    canvas = self.canvas_heatmap
    canvas.delete("all")
    self._heatmap_cells = []
    self._heatmap_hovered_item = None
    self._heatmap_layout_snapshot = {}
    w = max(260, canvas.winfo_width())
    h = max(220, canvas.winfo_height())
    canvas.configure(bg="#0f172a")

    if not self._last_results:
      canvas.create_text(120, 60, text="Heatmap will appear after loading data.", fill="#cbd5e1", anchor="w", font=("Segoe UI", 14, "bold"))
      return

    points = sorted(self._last_results)
    max_count = max((count for _, count in points), default=1)
    first_day = points[0][0]
    start = first_day - dt.timedelta(days=(first_day.weekday() + 1) % 7)
    day_map = {day: count for day, count in points}
    weeks = math.ceil(((points[-1][0] - start).days + 1) / 7)

    left = 38
    right = 10
    top = 6
    legend_height = 30
    band_header = 32
    band_gap = 14
    usable_w = max(80, w - left - right)
    usable_h = max(100, h - top - legend_height)

    candidates: list[tuple[int, int, int, int, int]] = []
    for band_count in range(1, min(4, weeks) + 1):
      columns = math.ceil(weeks / band_count)
      for candidate_gap in (3, 2, 1, 0):
        cell_w = math.floor((usable_w - ((columns - 1) * candidate_gap)) / columns)
        vertical_fixed = (band_count * band_header) + ((band_count - 1) * band_gap) + (band_count * 6 * candidate_gap)
        cell_h = math.floor((usable_h - vertical_fixed) / (band_count * 7))
        square = min(36, cell_w, cell_h)
        if square < 1:
          continue
        required_gap = 3 if square >= 15 else 2 if square >= 8 else 1 if square >= 3 else 0
        if candidate_gap != required_gap:
          continue
        shape_score = -abs((columns * square) - (7 * band_count * square))
        candidates.append((square, candidate_gap, shape_score, -band_count, band_count))

    square, cell_gap, _shape_score, _negative_band_count, band_count = max(candidates)
    columns_per_band = math.ceil(weeks / band_count)
    band_grid_height = (7 * square) + (6 * cell_gap)
    band_height = band_header + band_grid_height
    total_grid_height = (band_count * band_height) + ((band_count - 1) * band_gap)
    y0 = top + max(0, (usable_h - total_grid_height) // 2)
    self._heatmap_layout_snapshot = {
      "weeks": weeks,
      "bands": band_count,
      "columns_per_band": columns_per_band,
      "square": square,
      "cell_gap": cell_gap,
      "cell_count": len(day_map),
    }

    def color_for_count(value: int) -> str:
      if value <= 0:
        return "#1e293b"
      ratio = math.log1p(value) / math.log1p(max_count) if max_count else 0
      if ratio < 0.3:
        return "#0f766e"
      if ratio < 0.5:
        return "#14b8a6"
      if ratio < 0.72:
        return "#22c55e"
      return "#84cc16"

    weekday_labels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    range_font_size = max(6, min(9, round(square * 0.5)))
    weekday_font_size = max(5, min(8, round(square * 0.45)))
    legend_font_size = max(6, min(8, round(square * 0.5)))
    for band in range(band_count):
      first_week = band * columns_per_band
      last_week = min(weeks, first_week + columns_per_band) - 1
      if first_week > last_week:
        continue
      column_count = last_week - first_week + 1
      grid_width = (column_count * square) + ((column_count - 1) * cell_gap)
      x0 = left + max(0, (usable_w - grid_width) // 2)
      band_y = y0 + band * (band_height + band_gap)
      band_start = max(first_day, start + dt.timedelta(days=first_week * 7))
      band_end = min(points[-1][0], start + dt.timedelta(days=(last_week * 7) + 6))
      range_text = f"{band_start.strftime('%b %d')} – {band_end.strftime('%b %d, %Y')}"
      canvas.create_text(x0, band_y + 2, text=range_text, fill="#cbd5e1", anchor="nw", font=("Segoe UI", range_font_size, "bold"))
      month_columns: list[tuple[int, tuple[int, int], dt.date]] = []
      for week in range(first_week, last_week + 1):
        week_days = [start + dt.timedelta(days=(week * 7) + row) for row in range(7)]
        visible_days = [day for day in week_days if first_day <= day <= points[-1][0]]
        if not visible_days:
          continue
        month_counts: dict[tuple[int, int], int] = {}
        for day in visible_days:
          key = (day.year, day.month)
          month_counts[key] = month_counts.get(key, 0) + 1
        midpoint = visible_days[len(visible_days) // 2]
        owner = max(month_counts, key=lambda key: (month_counts[key], key == (midpoint.year, midpoint.month)))
        owner_day = next(day for day in visible_days if (day.year, day.month) == owner)
        month_columns.append((week - first_week, owner, owner_day))

      span_start = 0
      while span_start < len(month_columns):
        span_end = span_start
        while span_end + 1 < len(month_columns) and month_columns[span_end + 1][1] == month_columns[span_start][1]:
          span_end += 1
        first_column = month_columns[span_start][0]
        last_column = month_columns[span_end][0]
        span_x1 = x0 + first_column * (square + cell_gap)
        span_x2 = x0 + last_column * (square + cell_gap) + square
        month_day = month_columns[span_start][2]
        span_width = span_x2 - span_x1
        month_text = month_day.strftime("%b")
        if span_width < 12:
          month_text = month_text[0]
        month_font_size = max(5, min(9, round(square * 0.55), math.floor(span_width / max(1.8, len(month_text) * 0.65))))
        canvas.create_text((span_x1 + span_x2) / 2, band_y + 19, text=month_text, fill="#94a3b8", anchor="center", font=("Segoe UI", month_font_size, "bold"))
        canvas.create_line(span_x1, band_y + 28, span_x2, band_y + 28, fill="#334155", width=1)
        span_start = span_end + 1
      cells_y = band_y + band_header

      for row, label in enumerate(weekday_labels):
        y = cells_y + row * (square + cell_gap) + square / 2
        weekday_text = label if square >= 8 else label[0]
        canvas.create_text(5, y, text=weekday_text, fill="#64748b", anchor="w", font=("Segoe UI", weekday_font_size))

      for week in range(first_week, last_week + 1):
        column = week - first_week
        for row in range(7):
          day = start + dt.timedelta(days=week * 7 + row)
          if day not in day_map:
            continue
          x = x0 + column * (square + cell_gap)
          y = cells_y + row * (square + cell_gap)
          count = day_map[day]
          item = canvas.create_rectangle(x, y, x + square, y + square, fill=color_for_count(count), outline="")
          self._heatmap_cells.append((x, y, x + square, y + square, day, count, item))

    legend_y = h - 16
    legend_square = min(12, square)
    legend_width = 33 + (5 * (legend_square + 3)) + 34
    legend_x = max(8, (w - legend_width) // 2)
    canvas.create_text(legend_x, legend_y, text="Less", fill="#94a3b8", anchor="w", font=("Segoe UI", legend_font_size))
    for idx, color in enumerate(["#1e293b", "#0f766e", "#14b8a6", "#22c55e", "#84cc16"]):
      x = legend_x + 34 + idx * (legend_square + 3)
      canvas.create_rectangle(x, legend_y - (legend_square / 2), x + legend_square, legend_y + (legend_square / 2), fill=color, outline="")
    canvas.create_text(legend_x + 34 + 5 * (legend_square + 3) + 2, legend_y, text="More", fill="#94a3b8", anchor="w", font=("Segoe UI", legend_font_size))

  def _heatmap_summary_text(self) -> str:
    active_days = sum(1 for _day, count in self._last_results if count > 0)
    total = sum(count for _day, count in self._last_results)
    return f"{active_days} active days · {_format_number(total)} activities · hover for details"

  def _on_heatmap_motion(self, event) -> None:
    hit = next((cell for cell in self._heatmap_cells if cell[0] <= event.x <= cell[2] and cell[1] <= event.y <= cell[3]), None)
    if hit is None:
      self._clear_heatmap_hover()
      return
    _x1, _y1, _x2, _y2, day, count, item = hit
    if item == self._heatmap_hovered_item:
      return
    self._clear_heatmap_hover(restore_summary=False)
    self.canvas_heatmap.itemconfigure(item, outline="#f8fafc", width=2)
    self.canvas_heatmap.configure(cursor="hand2")
    self._heatmap_hovered_item = item
    activity_word = "activity" if count == 1 else "activities"
    self.lbl_heatmap_detail.configure(text=f"{day.strftime('%A, %b %d, %Y')} · {_format_number(count)} {activity_word}")

  def _on_heatmap_leave(self, _event=None) -> None:
    self._clear_heatmap_hover()

  def _clear_heatmap_hover(self, restore_summary: bool = True) -> None:
    if self._heatmap_hovered_item is not None:
      try:
        self.canvas_heatmap.itemconfigure(self._heatmap_hovered_item, outline="", width=1)
      except tk.TclError:
        pass
    self._heatmap_hovered_item = None
    self.canvas_heatmap.configure(cursor="")
    if restore_summary and self._last_results:
      self.lbl_heatmap_detail.configure(text=self._heatmap_summary_text())

  def _on_export_csv(self) -> None:
    if not self._last_results:
      messagebox.showinfo(APP_TITLE, "No activity data to export.")
      return
    path = filedialog.asksaveasfilename(
      title="Export Activity CSV",
      defaultextension=".csv",
      filetypes=[("CSV", "*.csv"), ("All Files", "*.*")],
      initialfile=f"gitea_activity_{self._last_username or 'user'}.csv",
    )
    if not path:
      return
    try:
      with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("date,count\n")
        for day, count in self._last_results:
          f.write(f"{day.isoformat()},{count}\n")
      self._log(f"Exported CSV: {path}")
    except Exception as e:
      messagebox.showerror(APP_TITLE, f"Failed to export CSV:\n{e}")

  def _on_close(self) -> None:
    try:
      self._save_config()
    except Exception:
      pass
    if self._busy:
      if not messagebox.askyesno(APP_TITLE, "A fetch is still running. Close the app anyway?"):
        return
    self.destroy()


def main() -> int:
  set_windows_app_user_model_id(APP_USER_MODEL_ID)
  app = GiteaActivityChartApp()
  app.mainloop()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
