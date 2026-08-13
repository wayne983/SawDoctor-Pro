# -*- coding: utf-8 -*-
"""
鋸片醫生管理系統 v8.0
=======================
完全獨立:雙擊即用,不需要後端伺服器、不需要瀏覽器。
直接讀 NAS 資料夾 → 顯示在視窗中。

功能:
  1. 月份分頁 - 看每個月各客戶進來的鋸片
  2. 進度追蹤 - 送廠/研磨中/OK回來/已出貨
  3. 派工清單 - 當日/本月,可直接列印
  4. PPT 產生 - 有補齒的鋸片自動找照片做 PPT

命名規則:
  3053080T(2005)3T2P反板鋼面
  │└──┘└┘└─┘  └─────────┘
  │  外徑 厚  齒數    工序段
  └── 前3碼=外徑, 中2碼=厚度(÷10), 後2-3碼=齒數
  括號內 = 編號/品牌
  3T = 補3齒, 2P = 補2座, 反板, 鋼面

OK 原則:資料夾內有 OK01/OK02... 任何 OK+數字 開頭檔案 = 研磨完成回來
"""
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from quote_domain import (
    PriceRule,
    QuoteLineDraft,
    apply_manual_quote,
    build_quote_line,
    parse_nonnegative_int,
)

# ─── 依賴檢查 ──────────────────────────────────────────────
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from tkinter.scrolledtext import ScrolledText
except ImportError:
    sys.exit("需要 Python Tkinter (通常內建)，請確認 Python 安裝完整。")

# ─── 路徑 ────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
DB_FILE = BASE / "sawblade.db"
CFG_FILE = BASE / "config.json"
LOG_FILE = BASE / "scan.log"
DEBUG_LOG = BASE / "scan_debug.log"

DEFAULT_CFG = {
    "scan_root": r"\\Ds418\鋸片醫生專用\公司電腦共用檔\0001顯微鏡檢查檔\檢查檔",
    "deadline_early": 10,
    "deadline_late": 12,
}

# ─── 正規化 ──────────────────────────────────────────────────
_NORM = str.maketrans({"(":"(", ")":")", "（":"(", "）":")", "Ｔ":"T", "ｔ":"T", "　":" "})
def normalize(s):
    s = s.translate(_NORM)
    s = re.sub(r"(\d)t(?=\(|\d|$)", r"\1T", s, flags=re.I)
    return s

YEAR_RE  = re.compile(r"^20\d{2}$")
MONTH_RE = re.compile(r"^(\d{1,2})月$")
MAIN_RE  = re.compile(r"^(\d{3})(\d{2})(\d{2,3})T\(([^)]+)\)(.*)$", re.I)
ALT_RE   = re.compile(r"^(\d{3})(\d{2})(\d{2,3})T([A-Za-z0-9]{1,8})(.*)$", re.I)
OK_RE    = re.compile(r"^(ok\d+|\d+ok)", re.I)
SKIP_EX  = {"派工清單","PPT輸出","PPT","備份","新增資料夾","#recycle","@eaDir"}
SKIP_KW  = ["報告書","檢查報告","照片彙整"]

def parse_name(name, customer):
    nm = normalize(name.strip())
    if not nm or nm.startswith((".","~$")): return None
    if nm in SKIP_EX: return None
    for k in SKIP_KW:
        if k in nm: return None
    if YEAR_RE.match(nm) or MONTH_RE.match(nm): return None

    for rx in (MAIN_RE, ALT_RE):
        m = rx.match(nm)
        if m:
            od, thk_s, teeth_s, brand, tail = m.groups()
            thk = f"{int(thk_s)/10:.1f}"
            teeth = str(int(teeth_s))
            tail = tail or ""
            st = parse_ops(tail)
            st.update({"od":od,"thickness":thk,"teeth":teeth,"brand_id":brand.strip(),"customer":customer})
            return st

    # 父目錄推斷
    return {"od":"","thickness":"","teeth":"","brand_id":nm,"customer":customer,
            "supp_teeth":"-","supp_seats":"-","fanban":"-","steel":"-","grind":"是","is_scrap":False}

def parse_ops(tail):
    d = {"supp_teeth":"-","supp_seats":"-","fanban":"-","steel":"-","grind":"是","is_scrap":False}
    m = re.search(r"(\d+)T", tail, re.I)
    if m: d["supp_teeth"] = m.group(1)
    m = re.search(r"(\d+)P", tail, re.I)
    if m: d["supp_seats"] = m.group(1)
    if "反板" in tail: d["fanban"] = "是"
    if "鋼面" in tail or "鋼片" in tail: d["steel"] = "是"
    if "報廢" in tail: d["is_scrap"] = True
    return d

def detect_ok(folder: Path):
    """回傳 (是否有OK, OK檔名清單)"""
    ok = []
    try:
        for f in folder.iterdir():
            if f.is_file() and (OK_RE.match(f.name) or OK_RE.match(f.stem)):
                ok.append(f.name)
    except: pass
    return bool(ok), ok

def add_bdays(start: datetime, n: int) -> datetime:
    d = start; added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5: added += 1
    return d

# ─── 設定 ────────────────────────────────────────────────────
def load_cfg():
    if CFG_FILE.exists():
        try:
            with open(CFG_FILE,"r",encoding="utf-8") as f: return json.load(f)
        except: pass
    return dict(DEFAULT_CFG)

def save_cfg(d):
    with open(CFG_FILE,"w",encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

# ─── DB ──────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_FILE), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS blades(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer TEXT, brand_id TEXT,
        od TEXT, thickness TEXT, teeth TEXT,
        supp_teeth TEXT DEFAULT '-', supp_seats TEXT DEFAULT '-',
        fanban TEXT DEFAULT '-', steel TEXT DEFAULT '-', grind TEXT DEFAULT '是',
        folder_path TEXT UNIQUE,
        raw_name TEXT,
        year INTEGER, month INTEGER,
        receipt_date TEXT,
        early_deadline TEXT, late_deadline TEXT,
        ok_date TEXT,
        status TEXT DEFAULT 'in_progress',
        created_at TEXT, updated_at TEXT
    )""")
    ensure_quote_schema(conn)
    conn.commit()
    return conn


class QuoteCollisionError(RuntimeError):
    """報價批次編號衝突，避免覆蓋既有快照。"""


@dataclass(frozen=True)
class PublishedQuoteOutput:
    """由安全發布器建立、可在交易失敗時確定清理的輸出檔案。"""

    path: Path
    file_identity: tuple[int, int]

    def is_current_publication(self):
        """目標路徑仍指向本交易發布的同一個檔案時才允許清理。"""
        try:
            current = self.path.stat()
        except FileNotFoundError:
            return False
        return (current.st_dev, current.st_ino) == self.file_identity


@dataclass(frozen=True)
class QuoteBatch:
    id: str
    customer: str
    month_range: str
    created_at: str
    created_by: str
    price_version_id: str
    subtotal: int
    output_file: str


_INITIAL_PRICE_VERSION_ID = "PV-20260813"
_INITIAL_PRICE_EFFECTIVE_FROM = "2026-08-13"
_INITIAL_PRICE_RULES = (
    (305, 305, 240, 150, 230),
    (355, 355, 280, 150, 230),
    (405, 455, 350, 150, 250),
)


def ensure_quote_schema(conn):
    """建立報價資料表並在空白資料庫寫入初始價目版本。"""
    conn.execute("""CREATE TABLE IF NOT EXISTS price_versions(
        id TEXT PRIMARY KEY, effective_from TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS price_rules(
        version_id TEXT NOT NULL, od_min INTEGER NOT NULL, od_max INTEGER NOT NULL,
        grinding_price INTEGER NOT NULL, tooth_price INTEGER NOT NULL, fanban_price INTEGER NOT NULL,
        PRIMARY KEY(version_id, od_min, od_max)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS quote_batches(
        id TEXT PRIMARY KEY, customer TEXT NOT NULL, month_range TEXT NOT NULL,
        created_at TEXT NOT NULL, created_by TEXT NOT NULL, price_version_id TEXT NOT NULL,
        subtotal INTEGER NOT NULL, output_file TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS quote_output_files(
        batch_id TEXT NOT NULL, format TEXT NOT NULL, filename TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(batch_id, format)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS quote_lines(
        id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, blade_id INTEGER NOT NULL,
        display_order INTEGER NOT NULL, spec TEXT NOT NULL, brand_id TEXT NOT NULL,
        source_grind TEXT NOT NULL, source_supp_teeth TEXT NOT NULL, source_fanban TEXT NOT NULL,
        suggested_grinding_qty INTEGER NOT NULL, suggested_grinding_unit INTEGER NOT NULL,
        suggested_tooth_qty INTEGER NOT NULL, suggested_tooth_unit INTEGER NOT NULL,
        suggested_fanban_qty INTEGER NOT NULL, suggested_fanban_unit INTEGER NOT NULL,
        suggested_subtotal INTEGER NOT NULL,
        grinding_qty INTEGER NOT NULL, grinding_unit INTEGER NOT NULL,
        tooth_qty INTEGER NOT NULL, tooth_unit INTEGER NOT NULL,
        fanban_qty INTEGER NOT NULL, fanban_unit INTEGER NOT NULL,
        subtotal INTEGER NOT NULL, note TEXT NOT NULL
    )""")
    existing_quote_line_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(quote_lines)")
    }
    for column in (
        "suggested_grinding_qty", "suggested_grinding_unit",
        "suggested_tooth_qty", "suggested_tooth_unit",
        "suggested_fanban_qty", "suggested_fanban_unit", "suggested_subtotal",
    ):
        if column not in existing_quote_line_columns:
            # 舊快照無從回推當時自動建議，因此保留 NULL；新寫入資料一律有明確值。
            conn.execute(f"ALTER TABLE quote_lines ADD COLUMN {column} INTEGER")
    created_at = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR IGNORE INTO price_versions(id, effective_from, created_at) VALUES (?, ?, ?)",
        (_INITIAL_PRICE_VERSION_ID, _INITIAL_PRICE_EFFECTIVE_FROM, created_at),
    )
    for rule in _INITIAL_PRICE_RULES:
        conn.execute(
            """INSERT OR IGNORE INTO price_rules(
                version_id, od_min, od_max, grinding_price, tooth_price, fanban_price
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (_INITIAL_PRICE_VERSION_ID, *rule),
        )
    conn.commit()


def load_effective_price_rules(conn, on_date):
    """依生效日讀取一個價目版本，並保留資料庫中的既有價格。"""
    if isinstance(on_date, datetime):
        on_date = on_date.date()
    if not isinstance(on_date, date):
        raise TypeError("on_date 必須是 date")
    version = conn.execute(
        """SELECT id, effective_from FROM price_versions
           WHERE effective_from <= ? ORDER BY effective_from DESC LIMIT 1""",
        (on_date.isoformat(),),
    ).fetchone()
    if version is None:
        return {}
    rules = conn.execute(
        """SELECT od_min, od_max, grinding_price, tooth_price, fanban_price
           FROM price_rules WHERE version_id = ? ORDER BY od_min""",
        (version[0],),
    ).fetchall()
    effective_from = date.fromisoformat(version[1])
    return {
        str(row[0]): PriceRule(
            version_id=version[0],
            effective_from=effective_from,
            od_min=row[0],
            od_max=row[1],
            grinding_price=row[2],
            tooth_price=row[3],
            fanban_price=row[4],
        )
        for row in rules
    }


def _quote_month_range(months):
    return ",".join(f"{int(year):04d}-{int(month):02d}" for year, month in months)


def preview_quote_batch_id(conn, now=None):
    """預覽下一個批次編號，供建立實際輸出檔名後再寫入快照。"""
    now = now or datetime.now()
    prefix = f"Q-{now:%y%m%d}-"
    existing = conn.execute(
        "SELECT id FROM quote_batches WHERE id LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    sequence = int(existing[0][-3:]) + 1 if existing else 1
    if sequence > 999:
        raise QuoteCollisionError("當日報價批次已超過 999 筆")
    return f"{prefix}{sequence:03d}"


def quote_output_filename(customer, month_range, batch_id, extension="xlsx"):
    """回傳報價批次唯一對應的客戶維修明細檔名。"""
    extension = str(extension).lower().lstrip(".")
    if extension not in {"xlsx", "pdf"}:
        raise ValueError("報價輸出格式僅支援 xlsx 或 pdf")
    return (
        f"客戶維修明細_{_safe_quote_filename_component(customer)}_"
        f"{_safe_quote_filename_component(month_range)}_{batch_id}.{extension}"
    )


def _normalise_quote_output_formats(output_formats):
    formats = tuple(str(output_format).lower().lstrip(".") for output_format in output_formats)
    if not formats:
        raise ValueError("至少選擇一種報價輸出格式")
    if len(set(formats)) != len(formats) or any(output_format not in {"xlsx", "pdf"} for output_format in formats):
        raise ValueError("報價輸出格式僅支援不重複的 xlsx 或 pdf")
    return formats


def quote_line_from_blade(blade, rules):
    """以目前生效價目建立草稿；無規則時保留為待人工填價。"""
    od = str(blade["od"] or "")
    rule = next(
        (
            candidate for candidate in rules.values()
            if candidate.od_min <= int(od) <= candidate.od_max
        ),
        None,
    ) if od.isdigit() else None
    if rule is not None:
        # 舊工單以「-」表示無補齒；計價草稿需要明確的 0，且不修改來源資料。
        quote_blade = dict(blade)
        if str(quote_blade.get("supp_teeth", "")).strip() in ("", "-"):
            quote_blade["supp_teeth"] = "0"
        line = build_quote_line(quote_blade, rule)
        return replace(line, source_supp_teeth=str(blade["supp_teeth"]))

    def quantity(value):
        try:
            return parse_nonnegative_int(value)
        except ValueError:
            return 0

    grind = str(blade["grind"])
    teeth = str(blade["supp_teeth"])
    fanban = str(blade["fanban"])
    return QuoteLineDraft(
        blade_id=parse_nonnegative_int(blade["id"]), customer=str(blade["customer"]),
        brand_id=str(blade["brand_id"]), od=od, thickness=str(blade["thickness"]),
        teeth=str(blade["teeth"]), spec=f"{od} x {blade['thickness']} x {blade['teeth']}T",
        source_grind=grind, source_supp_teeth=teeth, source_fanban=fanban,
        grinding_qty=1 if grind == "是" else 0, grinding_unit=0,
        tooth_qty=quantity(teeth), tooth_unit=0,
        fanban_qty=1 if fanban == "是" else 0, fanban_unit=0,
    )


def manual_only_repair_labels(blade):
    """找出不可自動報價的來源工序，交由技師在本次報價明確處理。"""
    labels = []
    seats = str(blade["supp_seats"] or "").strip()
    if seats and seats not in ("-", "0"):
        labels.append(f"補座 {seats}座")
    if str(blade["steel"] or "").strip() == "是":
        labels.append("鋼面")
    if str(blade["status"] or "").strip() == "scrapped" or bool(blade["is_scrap"] if "is_scrap" in blade.keys() else False):
        labels.append("報廢")
    raw_name = str(blade["raw_name"] or "") if "raw_name" in blade.keys() else ""
    if "特殊" in raw_name:
        labels.append("特殊")
    return tuple(labels)


def quote_line_validation_error(line, manual_labels=()):
    """回傳列入報價前仍需處理的原因；不改寫來源或自動計價人工工序。"""
    if not line.included:
        return ""
    if any(quantity and not unit for quantity, unit in (
        (line.grinding_qty, line.grinding_unit),
        (line.tooth_qty, line.tooth_unit),
        (line.fanban_qty, line.fanban_unit),
    )):
        return "待人工填價"
    if manual_labels and not line.note.strip():
        return "待人工確認：" + "、".join(manual_labels)
    return ""


def quote_line_with_manual_confirmation(line, manual_labels):
    """將技師對人工工序的處理說明明確帶入不可變的報價快照與 Excel 備註。"""
    if manual_labels and line.note.strip():
        return apply_manual_quote(
            line, note=f"人工確認（{'、'.join(manual_labels)}）：{line.note.strip()}"
        )
    return line


def save_quote_batch(
    conn, customer, months, lines, created_by, *, quote_date, output_file,
    batch_id=None, now=None, commit=True,
):
    """只保存已列入的確認明細；commit=False 時由呼叫端完成交易。"""
    if not isinstance(output_file, str) or not output_file.strip():
        raise ValueError("output_file 必須是非空字串")
    output_file = output_file.strip()
    batch_customer = str(customer)
    snapshot_lines = tuple(line for line in lines if line.included)
    if not snapshot_lines:
        raise ValueError("報價至少需要一筆列入的明細")
    if any(line.customer != batch_customer for line in snapshot_lines):
        raise ValueError("報價批次不得混用不同客戶的明細")
    now = now or datetime.now()
    generated_batch_id = preview_quote_batch_id(conn, now)
    if batch_id is None:
        batch_id = generated_batch_id
    elif batch_id != generated_batch_id:
        raise QuoteCollisionError("報價批次編號已變更，請重新確認後再產生")
    effective_rules = load_effective_price_rules(conn, quote_date)
    if not effective_rules:
        raise ValueError("報價日期沒有可用的價目版本")
    price_version_id = next(iter(effective_rules.values())).version_id
    subtotal = sum(line.subtotal for line in snapshot_lines)
    batch = QuoteBatch(
        id=batch_id,
        customer=batch_customer,
        month_range=_quote_month_range(months),
        created_at=now.isoformat(timespec="seconds"),
        created_by=str(created_by),
        price_version_id=price_version_id,
        subtotal=subtotal,
        output_file=output_file,
    )
    try:
        conn.execute(
            """INSERT INTO quote_batches(
                id, customer, month_range, created_at, created_by, price_version_id, subtotal, output_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                batch.id, batch.customer, batch.month_range, batch.created_at,
                batch.created_by, batch.price_version_id, batch.subtotal, batch.output_file,
            ),
        )
        for display_order, line in enumerate(snapshot_lines, start=1):
            conn.execute(
                """INSERT INTO quote_lines(
                    batch_id, blade_id, display_order, spec, brand_id,
                    source_grind, source_supp_teeth, source_fanban,
                    suggested_grinding_qty, suggested_grinding_unit,
                    suggested_tooth_qty, suggested_tooth_unit,
                    suggested_fanban_qty, suggested_fanban_unit, suggested_subtotal,
                    grinding_qty, grinding_unit, tooth_qty, tooth_unit,
                    fanban_qty, fanban_unit, subtotal, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    batch.id, line.blade_id, display_order, line.spec, line.brand_id,
                    line.source_grind, line.source_supp_teeth, line.source_fanban,
                    line.suggested_grinding_qty if line.suggested_grinding_qty is not None else line.grinding_qty,
                    line.suggested_grinding_unit if line.suggested_grinding_unit is not None else line.grinding_unit,
                    line.suggested_tooth_qty if line.suggested_tooth_qty is not None else line.tooth_qty,
                    line.suggested_tooth_unit if line.suggested_tooth_unit is not None else line.tooth_unit,
                    line.suggested_fanban_qty if line.suggested_fanban_qty is not None else line.fanban_qty,
                    line.suggested_fanban_unit if line.suggested_fanban_unit is not None else line.fanban_unit,
                    line.suggested_subtotal if line.suggested_subtotal is not None else line.subtotal,
                    line.grinding_qty, line.grinding_unit, line.tooth_qty, line.tooth_unit,
                    line.fanban_qty, line.fanban_unit, line.subtotal, line.note,
                ),
            )
        if commit:
            conn.commit()
    except sqlite3.IntegrityError as error:
        conn.rollback()
        raise QuoteCollisionError(f"報價批次 {batch_id} 已存在") from error
    return batch

def spec_str(b):
    od = b["od"] or ""; thk = b["thickness"] or ""; te = b["teeth"] or ""
    parts = []
    if od: parts.append(od)
    if thk:
        try:
            f = float(thk); f = f/10 if f>=10 else f
            parts.append(f"{f:.1f}T")
        except: parts.append(f"{thk}T")
    if te:
        try: parts.append(f"{int(te)}T")
        except: parts.append(f"{te}T")
    return " / ".join(parts)

def ops_str(b):
    out = ["研磨"]
    st = b["supp_teeth"] if isinstance(b,dict) else b["supp_teeth"]
    ss = b["supp_seats"] if isinstance(b,dict) else b["supp_seats"]
    fb = b["fanban"]    if isinstance(b,dict) else b["fanban"]
    sl = b["steel"]     if isinstance(b,dict) else b["steel"]
    if st and st not in ("-","0",""): out.append(f"補{st}齒")
    if ss and ss not in ("-","0",""): out.append(f"補{ss}座")
    if fb == "是": out.append("反板")
    if sl == "是": out.append("鋼面")
    return " / ".join(out)

def status_label(b):
    s = b["status"] if isinstance(b,dict) else b["status"]
    if s in ("complete","已出貨"): return "✅ 已出貨"
    if s == "scrapped": return "❌ 報廢"
    if s == "folder_missing": return "— 資料夾消失"
    ok_d = b["ok_date"] if isinstance(b,dict) else b["ok_date"]
    if ok_d: return "🔍 OK回來/待出貨"
    return "🔧 研磨中"

# ─── 掃描 ────────────────────────────────────────────────────
_scan_lock = threading.Lock()

def scan_nas(cfg, log_cb=None):
    if not _scan_lock.acquire(blocking=False):
        if log_cb: log_cb("掃描已在執行中,請稍候")
        return 0

    def _log(msg):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        if log_cb: log_cb(line)
        try:
            with open(LOG_FILE,"a",encoding="utf-8") as f: f.write(line+"\n")
        except: pass

    try:
        root = Path(cfg["scan_root"])
        if not root.exists():
            _log(f"❌ NAS 無法連線: {root}"); return 0

        early_d = int(cfg.get("deadline_early",10))
        late_d  = int(cfg.get("deadline_late",12))
        today   = datetime.today()

        seen = set()
        upserted = complete_new = 0

        with open(DEBUG_LOG,"w",encoding="utf-8") as dbg:
            dbg.write(f"=== scan {time.strftime('%Y-%m-%d %H:%M:%S')} root={root} ===\n")

        with get_db() as conn:
            for yr_dir in _ls(root):
                if not yr_dir.is_dir() or not YEAR_RE.match(yr_dir.name): continue
                year = int(yr_dir.name)
                for mo_dir in _ls(yr_dir):
                    if not mo_dir.is_dir(): continue
                    mm = MONTH_RE.match(mo_dir.name)
                    if not mm: continue
                    month = int(mm.group(1))
                    for cu_dir in _ls(mo_dir):
                        if not cu_dir.is_dir() or cu_dir.name in SKIP_EX: continue
                        customer = cu_dir.name
                        for wk_dir in _ls(cu_dir):
                            if not wk_dir.is_dir(): continue
                            parsed = parse_name(wk_dir.name, customer)
                            if not parsed:
                                _dbg(f"SKIP {wk_dir}"); continue

                            # 進貨日 = 工單資料夾的「建立時間」(fallback: 修改時間,再 fallback: 月份首日)
                            rd_dt = _folder_created(wk_dir, year, month)
                            receipt = rd_dt.strftime("%Y-%m-%d")
                            early = add_bdays(rd_dt, early_d).strftime("%Y-%m-%d")
                            late  = add_bdays(rd_dt, late_d).strftime("%Y-%m-%d")

                            has_ok, ok_files = detect_ok(wk_dir)
                            # 系統 2026/4 月開始啟用,之前的資料一律視為已出貨
                            is_legacy = (year < 2026) or (year == 2026 and month <= 3)

                            if parsed.get("is_scrap"):
                                status = "scrapped"; ok_date = ""
                            elif is_legacy:
                                status = "已出貨"
                                # 若有 OK 照片,用 OK 時間當完工日
                                ok_date = ""
                                for fn in ok_files:
                                    try:
                                        mt = (wk_dir/fn).stat().st_mtime
                                        ok_date = datetime.fromtimestamp(mt).strftime("%Y-%m-%d")
                                        break
                                    except: pass
                                if not ok_date:
                                    ok_date = rd_dt.strftime("%Y-%m-%d")
                            elif has_ok:
                                status = "complete"
                                # ok_date = 最早 OK 檔的修改日
                                ok_date = ""
                                for fn in ok_files:
                                    try:
                                        mt = (wk_dir/fn).stat().st_mtime
                                        ok_date = datetime.fromtimestamp(mt).strftime("%Y-%m-%d")
                                        break
                                    except: pass
                                if not ok_date: ok_date = today.strftime("%Y-%m-%d")
                                complete_new += 1
                            else:
                                status = "in_progress"; ok_date = ""

                            fp = str(wk_dir)
                            seen.add(fp)
                            now = time.strftime("%Y-%m-%d %H:%M:%S")

                            row = conn.execute("SELECT id,status,ok_date,receipt_date FROM blades WHERE folder_path=?",(fp,)).fetchone()
                            if row:
                                # 若已有 ok_date 則保留
                                final_ok = ok_date or (row["ok_date"] or "")
                                # 已完工/出貨保護
                                final_status = status
                                if row["status"] in ("complete","已出貨","scrapped") and not has_ok:
                                    final_status = row["status"]
                                    final_ok = row["ok_date"] or ok_date
                                conn.execute("""UPDATE blades SET
                                    customer=?,brand_id=?,od=?,thickness=?,teeth=?,
                                    supp_teeth=?,supp_seats=?,fanban=?,steel=?,grind=?,
                                    raw_name=?,year=?,month=?,receipt_date=?,
                                    early_deadline=?,late_deadline=?,
                                    ok_date=?,status=?,updated_at=? WHERE id=?""",
                                (parsed["customer"],parsed["brand_id"],
                                 parsed["od"],parsed["thickness"],parsed["teeth"],
                                 parsed["supp_teeth"],parsed["supp_seats"],
                                 parsed["fanban"],parsed["steel"],parsed["grind"],
                                 wk_dir.name,year,month,receipt,early,late,
                                 final_ok,final_status,now,row["id"]))
                            else:
                                conn.execute("""INSERT INTO blades(
                                    customer,brand_id,od,thickness,teeth,
                                    supp_teeth,supp_seats,fanban,steel,grind,
                                    folder_path,raw_name,year,month,receipt_date,
                                    early_deadline,late_deadline,ok_date,status,
                                    created_at,updated_at)
                                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (parsed["customer"],parsed["brand_id"],
                                 parsed["od"],parsed["thickness"],parsed["teeth"],
                                 parsed["supp_teeth"],parsed["supp_seats"],
                                 parsed["fanban"],parsed["steel"],parsed["grind"],
                                 fp,wk_dir.name,year,month,receipt,early,late,
                                 ok_date,status,now,now))
                            upserted += 1

            # 消失
            for r in conn.execute("SELECT id,folder_path FROM blades WHERE status='in_progress'").fetchall():
                if r["folder_path"] and r["folder_path"] not in seen:
                    if not Path(r["folder_path"]).exists():
                        conn.execute("UPDATE blades SET status='folder_missing',updated_at=? WHERE id=?",
                                     (time.strftime("%Y-%m-%d %H:%M:%S"),r["id"]))
            conn.commit()

        _log(f"✅ 掃描完成: 寫入 {upserted} 筆, 其中 {complete_new} 筆偵測到 OK")
        return upserted
    except Exception as e:
        _log(f"❌ 掃描異常: {e}\n{traceback.format_exc()}")
        return 0
    finally:
        _scan_lock.release()

def _ls(p):
    try: return list(p.iterdir())
    except: return []

def _folder_created(folder: Path, year: int, month: int) -> datetime:
    """回傳資料夾的進貨日:優先用 Windows 建立時間,fallback 修改時間,最後才用月份首日。
    如果建立時間的年月跟父目錄對不上(例如拷貝過的),改用資料夾內「非 OK 照片」最早時間。"""
    try:
        st = folder.stat()
        # Windows 的 ctime 是建立時間
        ct = datetime.fromtimestamp(st.st_ctime)
        mt = datetime.fromtimestamp(st.st_mtime)
        # 選兩者中較早的(通常建立較早)
        candidate = ct if ct <= mt else mt

        # 如果 candidate 的年月對得上目錄層,直接用
        if candidate.year == year and candidate.month == month:
            return candidate

        # 對不上(檔案拷貝/搬移過),改找資料夾內最早的非 OK 照片時間
        earliest = None
        for f in folder.iterdir():
            if not f.is_file(): continue
            if OK_RE.match(f.name) or OK_RE.match(f.stem): continue
            try:
                ft = datetime.fromtimestamp(f.stat().st_mtime)
                if ft.year == year and ft.month == month:
                    if earliest is None or ft < earliest:
                        earliest = ft
            except: pass
        if earliest:
            return earliest
        # 還是找不到就退回月份首日
        return datetime(year, month, 1)
    except Exception:
        try: return datetime(year, month, 1)
        except: return datetime.today()

def _dbg(msg):
    try:
        with open(DEBUG_LOG,"a",encoding="utf-8") as f: f.write(msg+"\n")
    except: pass

# ─── 派工清單 HTML ────────────────────────────────────────────
DISPATCH_HTML = BASE / "派工清單.html"

def gen_dispatch_html(rows, title="派工清單", mode="vendor"):
    """廠商對帳派工清單 — 直式 A4,支援電子勾選+回傳 JSON 檔"""
    import json as _json
    def yn(v): return "✓" if v=="是" else "—"
    def nd(v): return v if v and v not in ("-","0","") else "—"

    # 產生單號
    serial = f"D-{datetime.now().strftime('%y%m%d%H%M')}"

    # 先建立資料陣列 (供 JS 使用) — 相同客戶+規格+工序的整合成一列
    raw_items = []
    for b in rows:
        already_done = b["status"] in ("complete","已出貨") or bool(b["ok_date"])
        raw_items.append({
            "folder_path": b["folder_path"] if "folder_path" in b.keys() else "",
            "customer": b["customer"] or "",
            "brand_id": b["brand_id"] or "",
            "spec": spec_str(b),
            "grind": yn(b["grind"]),
            "supp_teeth": nd(b["supp_teeth"]),
            "supp_seats": nd(b["supp_seats"]),
            "fanban": yn(b["fanban"]),
            "steel": yn(b["steel"]),
            "receipt_date": b["receipt_date"] or "",
            "late_deadline": b["late_deadline"] or "",
            "already_done": already_done,
        })

    # 分組鍵 = 客戶 + 規格 + 工序(不含編號)
    def _group_key(r):
        return (r["customer"], r["spec"],
                r["grind"], r["supp_teeth"], r["supp_seats"],
                r["fanban"], r["steel"])

    # 保持原順序的分組
    grouped = {}
    order = []
    for r in raw_items:
        k = _group_key(r)
        if k not in grouped:
            grouped[k] = []
            order.append(k)
        grouped[k].append(r)

    items = []
    for i, k in enumerate(order, 1):
        members = grouped[k]
        # 以最早進貨日、最晚交期作為代表
        r0 = members[0]
        recs = [m["receipt_date"] for m in members if m["receipt_date"]]
        lates = [m["late_deadline"] for m in members if m["late_deadline"]]
        # 所有編號合併顯示,以「/」分隔
        brand_ids = [m["brand_id"] for m in members if m["brand_id"]]
        # 勾選狀態:全部都已完成才預先打勾
        all_done = all(m["already_done"] for m in members)

        items.append({
            "idx": i,
            "count": len(members),
            "folder_paths": [m["folder_path"] for m in members],
            "customer": r0["customer"],
            "brand_ids": brand_ids,
            "brand_display": " / ".join(brand_ids) if brand_ids else "-",
            "spec": r0["spec"],
            "grind": r0["grind"],
            "supp_teeth": r0["supp_teeth"],
            "supp_seats": r0["supp_seats"],
            "fanban": r0["fanban"],
            "steel": r0["steel"],
            "receipt_date": min(recs) if recs else "",
            "late_deadline": max(lates) if lates else "",
            "already_done": all_done,
            "checked": all_done,
        })

    items_json = _json.dumps(items, ensure_ascii=False)
    total = len(items)
    done_cnt = sum(1 for x in items if x["already_done"])

    # 組工序欄:如果有補齒/補座/反板/鋼面就顯示內容,否則顯示 —
    def ops_cell(x):
        tags = []
        if x["grind"] == "✓":      tags.append('<span class="tag grind">研</span>')
        if x["supp_teeth"] != "—": tags.append(f'<span class="tag teeth">補{x["supp_teeth"]}齒</span>')
        if x["supp_seats"] != "—": tags.append(f'<span class="tag seats">補{x["supp_seats"]}座</span>')
        if x["fanban"] == "✓":     tags.append('<span class="tag fan">反板</span>')
        if x["steel"] == "✓":      tags.append('<span class="tag steel">鋼面</span>')
        return "".join(tags) or "—"

    trs = ""
    for x in items:
        cls = "done" if x["checked"] else ""
        mark = "☑" if x["checked"] else "☐"
        cnt_badge = f'<span class="cnt-badge">×{x["count"]}</span>' if x["count"] > 1 else ""
        trs += f"""<tr data-idx="{x['idx']}" class="{cls}">
          <td class="chk">{mark}</td>
          <td class="num">{x['idx']}</td>
          <td class="cust">{x['customer']}{cnt_badge}</td>
          <td class="bid">{x['brand_display']}</td>
          <td class="spec">{x['spec']}</td>
          <td class="ops">{ops_cell(x)}</td>
          <td class="date">{x['receipt_date']}<br><small>→ {x['late_deadline']}</small></td>
          <td class="note"></td>
        </tr>"""

    html = f"""<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:"Microsoft JhengHei","PMingLiU",sans-serif;padding:10px 14px;color:#111;margin:0;background:#f4f6fa}}
.page{{max-width:210mm;margin:0 auto;background:white;padding:10mm 8mm;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.head{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px double #333;padding-bottom:6px;margin-bottom:8px}}
.head h1{{margin:0;font-size:22px;letter-spacing:2px}}
.head .sub{{font-size:13px;color:#555}}
.meta{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:10px 0;font-size:14px}}
.meta .box{{border:1px solid #999;padding:6px 10px;background:#fafafa}}
.meta .box b{{color:#333;margin-right:4px}}
.stats{{display:flex;gap:8px;font-size:15px;margin:8px 0 10px;flex-wrap:wrap}}
.stats .pill{{padding:4px 12px;border-radius:12px;font-weight:bold}}
.stats .total{{background:#1a3a5c;color:white}}
.stats .done{{background:#d4edda;color:#155724;border:1px solid #8fd19e}}
.stats .pending{{background:#fff3cd;color:#856404;border:1px solid #ffd56b}}
table{{width:100%;border-collapse:collapse;font-size:14px;table-layout:fixed}}
col.c-chk{{width:38px}} col.c-num{{width:32px}}
col.c-cust{{width:74px}} col.c-bid{{width:100px}}
col.c-spec{{width:110px}} col.c-ops{{width:auto}}
col.c-date{{width:90px}} col.c-note{{width:64px}}
th,td{{border:1px solid #555;padding:6px 6px;vertical-align:middle;overflow:hidden}}
th{{background:#e8eef7;font-weight:bold;text-align:center;font-size:13px;padding:8px 4px}}
td.chk{{text-align:center;font-size:26px;line-height:1;padding:4px;cursor:pointer;user-select:none}}
td.chk:hover{{background:#fffbd8}}
td.num{{text-align:center;color:#888;font-size:13px}}
td.date{{font-size:13px;text-align:center;white-space:nowrap;line-height:1.3}}
td.date small{{color:#c00;font-size:12px}}
td.cust{{font-weight:bold;text-align:center;font-size:15px}}
td.bid{{font-family:monospace;font-size:13px;text-align:center;word-break:break-all;line-height:1.3}}
td.spec{{text-align:center;font-size:13px;font-weight:bold}}
td.ops{{padding:4px}}
td.note{{background:#fffef0}}
.cnt-badge{{display:inline-block;background:#dc2626;color:white;border-radius:10px;padding:1px 7px;font-size:12px;font-weight:bold;margin-left:4px;vertical-align:middle}}
.tag{{display:inline-block;padding:2px 7px;margin:2px;font-size:13px;border-radius:4px;color:white;white-space:nowrap;font-weight:bold}}
.tag.grind{{background:#6b7280}}
.tag.teeth{{background:#ef4444}}
.tag.seats{{background:#f59e0b}}
.tag.fan{{background:#8b5cf6}}
.tag.steel{{background:#0ea5e9}}
tr.done{{background:#f0f0f0;color:#888}}
tr.done td.chk{{color:#080}}
tr.done td.ops .tag{{opacity:.55}}
tr:nth-child(even):not(.done){{background:#fcfcfc}}
.sign{{margin-top:14px;display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:14px}}
.sign .slot{{border:1px solid #666;padding:10px 14px;min-height:80px;position:relative}}
.sign .slot b{{display:block;margin-bottom:36px;color:#333;font-size:14px}}
.sign .slot small{{position:absolute;bottom:6px;right:10px;color:#999;font-size:11px}}
.notes{{margin-top:10px;border:1px solid #999;padding:8px 10px;font-size:13px;min-height:50px;background:#fffef0}}
.notes b{{display:block;margin-bottom:4px}}
.bar{{margin:0 0 10px;display:flex;gap:8px;flex-wrap:wrap;position:sticky;top:0;background:#f4f6fa;padding:8px 0;z-index:10;border-bottom:1px solid #ddd}}
.bar button{{padding:8px 14px;font-size:13px;border:none;border-radius:4px;cursor:pointer;color:white;background:#1a3a5c}}
.bar button:hover{{filter:brightness(1.15)}}
.bar .hint{{font-size:11px;color:#666;align-self:center;line-height:1.3}}
.bar .green{{background:#10b981}}
.bar .orange{{background:#f97316}}
.bar .gray{{background:#6b7280}}
.bar .red{{background:#dc2626}}
.info-box{{background:#eff6ff;border:1px solid #bfdbfe;padding:8px 12px;margin-bottom:10px;border-radius:6px;font-size:12px;color:#1e40af}}
.info-box b{{color:#1e3a8a}}
@media print{{
  .bar,.info-box{{display:none}}
  body{{padding:0;background:white}}
  .page{{box-shadow:none;padding:6mm 6mm;max-width:none}}
  @page{{size:A4 portrait;margin:8mm}}
  tr.done{{background:#e5e5e5 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  .tag{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
}}
</style></head><body>

<div class="bar" id="topbar">
  <button onclick="window.print()">🖨 列印紙本</button>
  <button class="green" onclick="checkAll(true)">✅ 全部勾選</button>
  <button class="gray" onclick="checkAll(false)">☐ 全部取消</button>
  <button class="orange" onclick="downloadReport()">📤 下載對帳回傳檔</button>
  <button class="red" onclick="resetAll()">🔄 重置</button>
  <span class="hint">
    <b>電腦勾選:</b>點擊勾選格即可切換 ☑/☐<br>
    <b>回傳:</b>勾完 → 下載對帳回傳檔 → 用 LINE/Email 傳回鋸片醫生
  </span>
</div>

<div class="page">

<div class="info-box">
  <b>📋 對帳單使用說明：</b>
  1. 廠商用電腦 / 平板開啟此檔，點擊「勾選」欄打勾 ☑<br>
  2. 勾選完畢按「📤 下載對帳回傳檔」會產生一個 .json 檔<br>
  3. 用 LINE / Email 把該 .json 檔傳回鋸片醫生<br>
  4. 若無法使用電子版，按「🖨 列印紙本」印出用原子筆打勾即可
</div>

<div class="head">
  <div>
    <h1>🪚 鋸片醫生 — {title}</h1>
    <div class="sub">HAWER SAWDOCTOR · 廠商對帳清單 (直式 A4)</div>
  </div>
  <div style="text-align:right;font-size:11px">
    列印日期:{datetime.now().strftime('%Y-%m-%d')}<br>
    單號:<b>{serial}</b>
  </div>
</div>

<div class="meta">
  <div class="box"><b>廠商：</b>______________________</div>
  <div class="box"><b>交貨日：</b>____________________</div>
  <div class="box"><b>收件人：</b>____________________</div>
</div>

<div class="stats">
  <span class="pill total">總件數 <span id="st-total">{total}</span></span>
  <span class="pill done">已完成 <span id="st-done">{done_cnt}</span></span>
  <span class="pill pending">未完成 <span id="st-pend">{total-done_cnt}</span></span>
  <span style="color:#888;align-self:center;font-size:11px">☑ = 已交回　☐ = 待交回</span>
</div>

<table>
<colgroup>
<col class="c-chk"><col class="c-num"><col class="c-cust"><col class="c-bid">
<col class="c-spec"><col class="c-ops"><col class="c-date"><col class="c-note">
</colgroup>
<thead><tr>
<th>勾選</th><th>#</th><th>客戶</th><th>編號</th>
<th>規格</th><th>維修工序</th><th>進貨日 / 交期</th><th>備註</th>
</tr></thead><tbody id="tb">{trs}</tbody></table>

<div class="sign">
  <div class="slot"><b>廠商簽收</b><small>簽名 / 蓋章 / 日期</small></div>
  <div class="slot"><b>鋸片醫生覆核</b><small>簽名 / 日期</small></div>
</div>

<div class="notes"><b>備註 / 異常說明:</b></div>

</div>

<script>
  const DATA = {items_json};
  const SERIAL = "{serial}";
  const TITLE = "{title}";

  function render() {{
    const tb = document.getElementById('tb');
    let done = 0;
    DATA.forEach(x => {{
      const tr = tb.querySelector(`tr[data-idx="${{x.idx}}"]`);
      if (!tr) return;
      const chk = tr.querySelector('.chk');
      chk.textContent = x.checked ? '☑' : '☐';
      tr.classList.toggle('done', !!x.checked);
      if (x.checked) done++;
    }});
    document.getElementById('st-done').textContent = done;
    document.getElementById('st-pend').textContent = DATA.length - done;
  }}

  // 點勾選欄或整列切換
  document.querySelectorAll('#tb tr').forEach(tr => {{
    const idx = parseInt(tr.dataset.idx);
    const chk = tr.querySelector('.chk');
    if (chk) {{
      chk.addEventListener('click', e => {{
        e.stopPropagation();
        const item = DATA.find(x => x.idx === idx);
        if (item) {{ item.checked = !item.checked; render(); }}
      }});
    }}
  }});

  function checkAll(val) {{
    DATA.forEach(x => x.checked = val);
    render();
  }}

  function resetAll() {{
    if (!confirm('確定要重置成初始狀態?')) return;
    DATA.forEach(x => x.checked = x.already_done);
    render();
  }}

  function downloadReport() {{
    const vendor = prompt('請輸入廠商名稱 (如:研磨廠A):', '') || '未填';
    const now = new Date();
    const pad = n => String(n).padStart(2,'0');
    const stamp = `${{now.getFullYear()}}${{pad(now.getMonth()+1)}}${{pad(now.getDate())}}_${{pad(now.getHours())}}${{pad(now.getMinutes())}}`;
    const report = {{
      type: "sawdoctor_dispatch_report",
      version: "1.0",
      serial: SERIAL,
      title: TITLE,
      vendor: vendor,
      reported_at: now.toISOString(),
      total: DATA.length,
      done: DATA.filter(x=>x.checked).length,
      items: DATA.map(x => ({{
        idx: x.idx,
        count: x.count,
        folder_paths: x.folder_paths,
        customer: x.customer,
        brand_ids: x.brand_ids,
        brand_display: x.brand_display,
        spec: x.spec,
        checked: x.checked,
      }}))
    }};
    const blob = new Blob([JSON.stringify(report, null, 2)], {{type:'application/json'}});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `對帳回傳_${{vendor}}_${{stamp}}.json`;
    a.click();
    alert(`已下載對帳回傳檔：\\n${{a.download}}\\n\\n請用 LINE 或 Email 傳回鋸片醫生！`);
  }}

  render();
</script>
</body></html>"""
    with open(DISPATCH_HTML,"w",encoding="utf-8") as f: f.write(html)
    return DISPATCH_HTML

# ─── 派工清單 Excel / Word 匯出 ──────────────────────────────
def _group_for_export(rows):
    """跟 HTML 一樣的合併邏輯,回傳 list of dict"""
    raw = []
    for b in rows:
        already_done = b["status"] in ("complete","已出貨") or bool(b["ok_date"])
        raw.append({
            "folder_path": b["folder_path"] if "folder_path" in b.keys() else "",
            "customer": b["customer"] or "",
            "brand_id": b["brand_id"] or "",
            "spec": spec_str(b),
            "supp_teeth": b["supp_teeth"] if b["supp_teeth"] not in ("-","0","",None) else "",
            "supp_seats": b["supp_seats"] if b["supp_seats"] not in ("-","0","",None) else "",
            "fanban": "是" if b["fanban"]=="是" else "",
            "steel": "是" if b["steel"]=="是" else "",
            "receipt_date": b["receipt_date"] or "",
            "late_deadline": b["late_deadline"] or "",
            "already_done": already_done,
            "status": b["status"],
        })
    def k(r): return (r["customer"], r["spec"], r["supp_teeth"], r["supp_seats"], r["fanban"], r["steel"])
    grouped = {}; order = []
    for r in raw:
        kk = k(r)
        if kk not in grouped: grouped[kk] = []; order.append(kk)
        grouped[kk].append(r)
    out = []
    for i, kk in enumerate(order, 1):
        m = grouped[kk]
        out.append({
            "idx": i, "count": len(m),
            "customer": m[0]["customer"],
            "brand_display": " / ".join(x["brand_id"] for x in m if x["brand_id"]),
            "spec": m[0]["spec"],
            "supp_teeth": m[0]["supp_teeth"],
            "supp_seats": m[0]["supp_seats"],
            "fanban": m[0]["fanban"],
            "steel": m[0]["steel"],
            "receipt_date": min((x["receipt_date"] for x in m if x["receipt_date"]), default=""),
            "late_deadline": max((x["late_deadline"] for x in m if x["late_deadline"]), default=""),
            "all_done": all(x["already_done"] for x in m),
        })
    return out

def export_dispatch_excel(rows, title):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    items = _group_for_export(rows)
    wb = Workbook(); ws = wb.active; ws.title = "派工清單"
    thin = Side(style="thin", color="666666")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left   = Alignment(horizontal="left",   vertical="center", wrap_text=True)
    bold = Font(bold=True, size=12, name="微軟正黑體")
    title_font = Font(bold=True, size=18, name="微軟正黑體")
    head_font  = Font(bold=True, size=11, name="微軟正黑體", color="FFFFFF")
    head_fill  = PatternFill("solid", fgColor="1A3A5C")
    done_fill  = PatternFill("solid", fgColor="E5E7EB")
    note_fill  = PatternFill("solid", fgColor="FFFBEB")

    # 標題
    ws.merge_cells("A1:J1")
    ws["A1"] = f"鋸片醫生 — {title}"; ws["A1"].font = title_font; ws["A1"].alignment = center
    ws.row_dimensions[1].height = 28
    # 表頭資訊
    ws["A2"] = f"列印日期:{datetime.now().strftime('%Y-%m-%d')}"
    ws["E2"] = f"單號:D-{datetime.now().strftime('%y%m%d%H%M')}"
    ws["A2"].font = Font(size=10); ws["E2"].font = Font(size=10)
    ws["A3"] = "廠商:"; ws["C3"] = ""
    ws["E3"] = "交貨日:"; ws["G3"] = ""
    ws["I3"] = "收件人:"
    for c in ("A3","E3","I3"): ws[c].font = bold
    ws["C3"].border = ws["G3"].border = Border(bottom=Side(style="thin"))

    # 表頭列
    headers = ["勾選","#","客戶","編號","規格","補齒","補座","反板","鋼面","進貨日 / 交期"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=5, column=col, value=h)
        cell.font = head_font; cell.fill = head_fill
        cell.alignment = center; cell.border = border
    ws.row_dimensions[5].height = 24

    # 內容
    for i, x in enumerate(items, 1):
        r = 5 + i
        cust_disp = x["customer"] + (f" ×{x['count']}" if x["count"]>1 else "")
        date_disp = f"{x['receipt_date']}\n→ {x['late_deadline']}"
        vals = ["☑" if x["all_done"] else "☐", x["idx"], cust_disp, x["brand_display"],
                x["spec"], x["supp_teeth"] or "—", x["supp_seats"] or "—",
                x["fanban"] or "—", x["steel"] or "—", date_disp]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=col, value=v)
            c.alignment = center; c.border = border
            c.font = Font(size=11, name="微軟正黑體", bold=(col==3))
            if x["all_done"]:
                c.fill = done_fill
        ws.row_dimensions[r].height = 32

    # 統計
    last = 5 + len(items) + 2
    total = len(items); done = sum(1 for x in items if x["all_done"])
    ws.cell(row=last, column=1, value=f"總件數: {total}    已完成: {done}    未完成: {total-done}").font = bold
    ws.merge_cells(start_row=last, start_column=1, end_row=last, end_column=10)
    # 簽收區
    sign_r = last + 2
    ws.cell(row=sign_r, column=1, value="廠商簽收:"); ws.cell(row=sign_r, column=1).font = bold
    ws.merge_cells(start_row=sign_r, start_column=2, end_row=sign_r+2, end_column=5)
    ws.cell(row=sign_r, column=6, value="鋸片醫生覆核:"); ws.cell(row=sign_r, column=6).font = bold
    ws.merge_cells(start_row=sign_r, start_column=7, end_row=sign_r+2, end_column=10)
    for r in range(sign_r, sign_r+3):
        for col in range(1, 11):
            c = ws.cell(row=r, column=col); c.border = border
    # 備註
    nr = sign_r + 4
    ws.cell(row=nr, column=1, value="備註 / 異常說明:").font = bold
    ws.merge_cells(start_row=nr, start_column=1, end_row=nr, end_column=10)
    ws.merge_cells(start_row=nr+1, start_column=1, end_row=nr+3, end_column=10)
    for r in range(nr+1, nr+4):
        for col in range(1, 11):
            c = ws.cell(row=r, column=col); c.border = border; c.fill = note_fill

    # 欄寬
    widths = [6, 5, 12, 16, 14, 7, 7, 7, 7, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64+i)].width = w

    # 列印設定:A4 直式
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
    ws.page_margins.left = 0.4; ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5;  ws.page_margins.bottom = 0.5
    ws.print_options.horizontalCentered = True
    ws.print_title_rows = "5:5"

    safe_title = title.replace("/","-").replace(" ","_")
    out = BASE / f"派工清單_{safe_title}_{datetime.now().strftime('%y%m%d%H%M')}.xlsx"
    wb.save(out)
    return out


def _safe_quote_filename_component(value):
    """將客戶資料轉為可安全使用於 Windows 檔名的片段。"""
    unsafe = '<>:"/\\|?*'
    cleaned = "".join("-" if char in unsafe else char for char in str(value).strip())
    return cleaned or "未命名客戶"


def publish_quote_output(target, write_temporary_file):
    """以暫存檔與不覆寫的目標建立，安全發布一個報價輸出檔案。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=".tmp", dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        write_temporary_file(temporary)
        if not temporary.is_file():
            raise RuntimeError("報價匯出未產生暫存檔案")
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise QuoteCollisionError(f"報價單號的輸出檔案已存在：{target.name}") from error
        published = target.stat()
        return PublishedQuoteOutput(target, (published.st_dev, published.st_ino))
    finally:
        if temporary.exists():
            temporary.unlink()


def export_customer_quote_excel(output_dir, batch, lines):
    """匯出客戶維修明細；每支鋸片維持一列，不合併報價金額。"""
    from itertools import groupby

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    included_lines = tuple(line for line in lines if line.included)
    if any(line.customer != batch.customer for line in included_lines):
        raise ValueError("客戶維修明細不得混用不同客戶的報價列")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered_lines = sorted(included_lines, key=lambda line: (line.spec, line.brand_id, line.blade_id))
    generated_on = datetime.now()

    wb = Workbook()
    ws = wb.active
    ws.title = "客戶維修明細"
    thin = Side(style="thin", color="666666")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    title_font = Font(bold=True, size=18, name="微軟正黑體")
    bold_font = Font(bold=True, size=11, name="微軟正黑體")
    body_font = Font(size=11, name="微軟正黑體")
    header_font = Font(bold=True, size=11, name="微軟正黑體", color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1A3A5C")
    group_fill = PatternFill("solid", fgColor="D9EAF7")
    unit_fill = PatternFill("solid", fgColor="EEF5FB")
    total_fill = PatternFill("solid", fgColor="FFF2CC")

    ws.merge_cells("A1:H1")
    ws["A1"] = "鋸片醫生－客戶維修明細（未稅）"
    ws["A1"].font = title_font
    ws["A1"].alignment = center
    ws["A2"] = f"客戶：{batch.customer}"
    ws["C2"] = f"報價單號：{batch.id}"
    ws["E2"] = f"月份範圍：{batch.month_range}"
    ws["G2"] = f"產生日期：{generated_on:%Y-%m-%d}"
    for cell in ("A2", "C2", "E2", "G2"):
        ws[cell].font = body_font

    headers = ["項次", "規格", "研磨", "補齒", "補座", "反板校正", "小計 NT$", "備註"]
    row_number = 4
    item_number = 1
    for spec, spec_lines in groupby(ordered_lines, key=lambda line: line.spec):
        group_lines = list(spec_lines)
        ws.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=8)
        group_cell = ws.cell(row=row_number, column=1, value=f"規格：{spec}")
        group_cell.font = bold_font
        group_cell.fill = group_fill
        group_cell.alignment = left
        group_cell.border = border
        for column in range(2, 9):
            ws.cell(row=row_number, column=column).border = border
        row_number += 1

        for column, header in enumerate(headers, start=1):
            cell = ws.cell(row=row_number, column=column, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border
        row_number += 1

        def actual_units(quantity_attr, unit_attr):
            units = []
            for line in group_lines:
                if getattr(line, quantity_attr) and getattr(line, unit_attr) not in units:
                    units.append(getattr(line, unit_attr))
            return " / ".join(f"${unit}" for unit in units)

        unit_values = ["單價", "", actual_units("grinding_qty", "grinding_unit"),
                       actual_units("tooth_qty", "tooth_unit"), "",
                       actual_units("fanban_qty", "fanban_unit"), "", ""]
        for column, value in enumerate(unit_values, start=1):
            cell = ws.cell(row=row_number, column=column, value=value)
            cell.font = body_font
            cell.fill = unit_fill
            cell.alignment = center
            cell.border = border
        row_number += 1

        for line in group_lines:
            remark = line.brand_id
            if line.note.strip():
                remark += f"\n{line.note.strip()}"
            values = [
                item_number,
                line.spec,
                line.grinding_qty or "",
                line.tooth_qty or "",
                "",
                line.fanban_qty or "",
                line.subtotal,
                remark,
            ]
            for column, value in enumerate(values, start=1):
                cell = ws.cell(row=row_number, column=column, value=value)
                cell.font = body_font
                cell.alignment = center if column != 8 else left
                cell.border = border
            ws.row_dimensions[row_number].height = 24
            row_number += 1
            item_number += 1

    ws.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=6)
    total_cell = ws.cell(row=row_number, column=1, value="未稅總計")
    total_cell.font = bold_font
    total_cell.fill = total_fill
    total_cell.alignment = center
    for column in range(1, 7):
        ws.cell(row=row_number, column=column).border = border
        ws.cell(row=row_number, column=column).fill = total_fill
    total_value_cell = ws.cell(row=row_number, column=7, value=sum(line.subtotal for line in ordered_lines))
    total_value_cell.font = bold_font
    total_value_cell.fill = total_fill
    total_value_cell.alignment = center
    total_value_cell.border = border
    note_cell = ws.cell(row=row_number, column=8)
    note_cell.fill = total_fill
    note_cell.border = border

    row_number += 1
    ws.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=8)
    date_cell = ws.cell(row=row_number, column=1, value=f"產生日期：{generated_on:%Y-%m-%d}")
    date_cell.font = body_font
    date_cell.alignment = left

    for column, width in enumerate([8, 24, 10, 10, 10, 12, 14, 18], start=1):
        ws.column_dimensions[chr(64 + column)].width = width
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5
    ws.print_options.horizontalCentered = True

    filename = quote_output_filename(batch.customer, batch.month_range, batch.id, "xlsx")
    output = output_dir / filename
    return publish_quote_output(output, wb.save)


def save_and_export_customer_quote(
    conn, output_dir, customer, months, lines, created_by, *, quote_date,
    now=None, output_formats=("xlsx",), exporters=None,
):
    """在同一交易中建立快照與所選輸出；任一步驟失敗即取消兩邊結果。"""
    if conn.in_transaction:
        raise RuntimeError("產生報價前資料庫不得有未完成的交易")
    formats = _normalise_quote_output_formats(output_formats)
    exporters = dict(exporters or {})
    exporters.setdefault("xlsx", export_customer_quote_excel)
    missing_formats = [output_format for output_format in formats if output_format not in exporters]
    if missing_formats:
        raise ValueError(f"缺少報價輸出器：{', '.join(missing_formats)}")
    now = now or datetime.now()
    output_dir = Path(output_dir)
    targets = {}
    created_outputs = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        batch_id = preview_quote_batch_id(conn, now)
        month_range = _quote_month_range(months)
        filenames = {
            output_format: quote_output_filename(customer, month_range, batch_id, output_format)
            for output_format in formats
        }
        targets = {
            output_format: output_dir / filename for output_format, filename in filenames.items()
        }
        for output_format, target in targets.items():
            if target.exists():
                raise QuoteCollisionError(f"同名 {output_format.upper()} 已存在，請重新確認後再產生")
        output_file = filenames["xlsx"] if "xlsx" in filenames else filenames["pdf"]
        batch = save_quote_batch(
            conn, customer, months, lines, created_by,
            quote_date=quote_date, output_file=output_file,
            batch_id=batch_id, now=now, commit=False,
        )
        outputs = {}
        for output_format in formats:
            target = targets[output_format]
            try:
                published_output = exporters[output_format](output_dir, batch, lines)
            except Exception:
                # 匯出器尚未成功安全發布時，交易端沒有檔案所有權可清理。
                raise
            if not isinstance(published_output, PublishedQuoteOutput):
                raise RuntimeError(f"{output_format.upper()} 匯出器必須使用安全發布器")
            output = published_output.path
            if output.resolve() != target.resolve() or not target.is_file():
                raise RuntimeError(f"{output_format.upper()} 匯出未產生預期的報價檔案")
            created_outputs.append(published_output)
            outputs[output_format] = target
            conn.execute(
                "INSERT INTO quote_output_files(batch_id, format, filename, created_at) VALUES (?, ?, ?, ?)",
                (batch.id, output_format, target.name, batch.created_at),
            )
        try:
            conn.commit()
        except Exception as error:
            conn.rollback()
            raise RuntimeError("資料庫提交失敗，報價快照與 Excel 已取消") from error
        return batch, outputs
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        for created_output in created_outputs:
            if created_output.is_current_publication():
                created_output.path.unlink()
        raise


def export_dispatch_word(rows, title):
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.table import WD_ALIGN_VERTICAL
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    items = _group_for_export(rows)
    doc = Document()
    # 直式 A4
    sec = doc.sections[0]
    sec.page_height = Cm(29.7); sec.page_width = Cm(21)
    sec.top_margin = Cm(1.2); sec.bottom_margin = Cm(1.2)
    sec.left_margin = Cm(1.2); sec.right_margin = Cm(1.2)

    # 標題
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run(f"鋸片醫生 — {title}")
    r.font.size = Pt(20); r.font.bold = True; r.font.name = "微軟正黑體"
    r._element.rPr.rFonts.set(qn('w:eastAsia'), '微軟正黑體')

    # 副標 + 單號
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r2 = p.add_run(f"列印日期:{datetime.now().strftime('%Y-%m-%d')}　單號:D-{datetime.now().strftime('%y%m%d%H%M')}")
    r2.font.size = Pt(10); r2.font.name = "微軟正黑體"
    r2._element.rPr.rFonts.set(qn('w:eastAsia'), '微軟正黑體')

    # 表頭資料
    info = doc.add_paragraph()
    ir = info.add_run("廠商:_______________  　　交貨日:_______________  　　收件人:_______________")
    ir.font.size = Pt(11); ir.font.name = "微軟正黑體"
    ir._element.rPr.rFonts.set(qn('w:eastAsia'), '微軟正黑體')

    total = len(items); done = sum(1 for x in items if x["all_done"])
    s = doc.add_paragraph()
    sr = s.add_run(f"總件數 {total}　|　已完成 {done}　|　未完成 {total-done}")
    sr.font.size = Pt(12); sr.font.bold = True; sr.font.name = "微軟正黑體"
    sr._element.rPr.rFonts.set(qn('w:eastAsia'), '微軟正黑體')

    # 表格
    headers = ["勾選","#","客戶","編號","規格","補齒","補座","反板","鋼面","進貨日/交期"]
    table = doc.add_table(rows=1+len(items), cols=len(headers))
    table.style = "Table Grid"
    # 寬度設定
    widths = [Cm(1.2), Cm(0.9), Cm(1.8), Cm(2.5), Cm(2.4), Cm(1.1), Cm(1.1), Cm(1.1), Cm(1.1), Cm(2.6)]
    for i, w in enumerate(widths):
        for cell in table.columns[i].cells:
            cell.width = w

    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        cell = hdr_cells[i]
        cell.text = ""
        para = cell.paragraphs[0]; para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(h)
        run.font.size = Pt(11); run.font.bold = True; run.font.name = "微軟正黑體"
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '微軟正黑體')
        # 表頭背景色
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), '1A3A5C'); shd.set(qn('w:val'), 'clear')
        tcPr.append(shd)
        for run in para.runs:
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    for i, x in enumerate(items, 1):
        cells = table.rows[i].cells
        cust = x["customer"] + (f" ×{x['count']}" if x["count"]>1 else "")
        date_disp = f"{x['receipt_date']}\n→ {x['late_deadline']}"
        vals = ["☑" if x["all_done"] else "☐", str(x["idx"]), cust, x["brand_display"],
                x["spec"], x["supp_teeth"] or "—", x["supp_seats"] or "—",
                x["fanban"] or "—", x["steel"] or "—", date_disp]
        for j, v in enumerate(vals):
            cell = cells[j]; cell.text = ""
            for line in str(v).split("\n"):
                p = cell.add_paragraph() if cell.paragraphs[0].text else cell.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(line)
                run.font.size = Pt(10); run.font.name = "微軟正黑體"
                if j == 2: run.font.bold = True  # 客戶粗體
                if j == 0: run.font.size = Pt(16)  # 勾選大一點
                run._element.rPr.rFonts.set(qn('w:eastAsia'), '微軟正黑體')
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if x["all_done"]:
                tcPr = cell._tc.get_or_add_tcPr()
                shd = OxmlElement('w:shd')
                shd.set(qn('w:fill'), 'E5E7EB'); shd.set(qn('w:val'), 'clear')
                tcPr.append(shd)

    doc.add_paragraph()
    sign = doc.add_paragraph()
    sr2 = sign.add_run("廠商簽收:_____________________________   鋸片醫生覆核:_____________________________")
    sr2.font.size = Pt(11); sr2.font.name = "微軟正黑體"
    sr2._element.rPr.rFonts.set(qn('w:eastAsia'), '微軟正黑體')
    note_p = doc.add_paragraph()
    nr = note_p.add_run("備註 / 異常說明:")
    nr.font.size = Pt(11); nr.font.bold = True; nr.font.name = "微軟正黑體"
    nr._element.rPr.rFonts.set(qn('w:eastAsia'), '微軟正黑體')

    safe_title = title.replace("/","-").replace(" ","_")
    out = BASE / f"派工清單_{safe_title}_{datetime.now().strftime('%y%m%d%H%M')}.docx"
    doc.save(str(out))
    return out


# ─── 儀表板 Excel 匯出 ────────────────────────────────────────
def export_dashboard_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from collections import Counter

    today = datetime.today().strftime("%Y-%m-%d")
    with get_db() as c:
        all_rows = c.execute("SELECT * FROM blades WHERE status!='folder_missing'").fetchall()
    active = [b for b in all_rows
              if (b["year"] or 0) > 2026 or ((b["year"] or 0)==2026 and (b["month"] or 0)>=4)]

    total = len(all_rows); act_tot = len(active)
    shipped = sum(1 for b in active if b["status"] in ("complete","已出貨"))
    okback  = sum(1 for b in active if b["ok_date"] and b["status"]=="in_progress")
    grinding= sum(1 for b in active if b["status"]=="in_progress" and not b["ok_date"])
    overdue = sum(1 for b in active if b["status"]=="in_progress" and b["late_deadline"] and b["late_deadline"]<today)
    scrap   = sum(1 for b in all_rows if b["status"]=="scrapped")

    wb = Workbook()
    thin = Side(style="thin", color="666666")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    bold = Font(bold=True, size=12, name="微軟正黑體")
    title_font = Font(bold=True, size=16, name="微軟正黑體", color="FFFFFF")
    head_font  = Font(bold=True, size=11, name="微軟正黑體", color="FFFFFF")
    title_fill = PatternFill("solid", fgColor="1A3A5C")
    head_fill  = PatternFill("solid", fgColor="3B82F6")

    # ── Sheet 1: 總覽 KPI ─────────────────────────
    ws = wb.active; ws.title = "總覽 KPI"
    ws.merge_cells("A1:D1")
    ws["A1"] = f"鋸片醫生 — 儀表板總覽 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    ws["A1"].font = title_font; ws["A1"].alignment = center; ws["A1"].fill = title_fill
    ws.row_dimensions[1].height = 28

    kpi = [
        ("項目", "件數", "說明", ""),
        ("📦 4月起總件數", act_tot, "系統啟用後的全部件數", ""),
        ("🔧 研磨中",     grinding, "送出研磨,還沒看到OK照片", ""),
        ("🔍 OK回來待出貨", okback, "已偵測到OK照片,可安排出貨", ""),
        ("✅ 已出貨",     shipped, "已標記出貨完成", ""),
        ("⚠️ 逾期件數",   overdue, "超過最晚交期還未完成", ""),
        ("❌ 報廢件數",   scrap, "判定為報廢", ""),
        ("📚 歷史總件數",  total, "含 2026/3 月以前的歷史資料", ""),
    ]
    for r, row in enumerate(kpi, 2):
        for col, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=col, value=v)
            cell.alignment = center; cell.border = border
            if r == 2:
                cell.font = head_font; cell.fill = head_fill
            else:
                cell.font = Font(size=12, bold=(col<=2), name="微軟正黑體")
    for col, w in enumerate([24, 12, 36, 8], 1):
        ws.column_dimensions[chr(64+col)].width = w

    # ── Sheet 2: 月份分布 ──────────────────────────
    ws2 = wb.create_sheet("月份分布")
    ws2.merge_cells("A1:E1")
    ws2["A1"] = "月份分布(全部)"; ws2["A1"].font = title_font; ws2["A1"].fill = title_fill
    ws2["A1"].alignment = center; ws2.row_dimensions[1].height = 24

    buckets = {}
    for b in all_rows:
        y, m = b["year"], b["month"]
        if not y or not m: continue
        key = f"{y}/{m:02d}"
        buckets.setdefault(key, {"done":0,"ok":0,"grind":0,"scrap":0})
        if b["status"]=="scrapped": buckets[key]["scrap"] += 1
        elif b["status"] in ("complete","已出貨"): buckets[key]["done"] += 1
        elif b["ok_date"] and b["status"]=="in_progress": buckets[key]["ok"] += 1
        else: buckets[key]["grind"] += 1

    headers = ["月份","研磨中","OK回來","已出貨","報廢"]
    for col, h in enumerate(headers, 1):
        c = ws2.cell(row=2, column=col, value=h)
        c.font = head_font; c.fill = head_fill; c.alignment = center; c.border = border
    for i, k in enumerate(sorted(buckets.keys()), 1):
        v = buckets[k]
        for col, val in enumerate([k, v["grind"], v["ok"], v["done"], v["scrap"]], 1):
            c = ws2.cell(row=2+i, column=col, value=val)
            c.alignment = center; c.border = border; c.font = Font(size=11, name="微軟正黑體")
    for col, w in enumerate([14, 12, 12, 12, 12], 1):
        ws2.column_dimensions[chr(64+col)].width = w

    # ── Sheet 3: 客戶排行(本月起) ────────────────
    ws3 = wb.create_sheet("客戶排行")
    ws3.merge_cells("A1:C1")
    ws3["A1"] = "客戶排行(2026/4月起)"
    ws3["A1"].font = title_font; ws3["A1"].fill = title_fill; ws3["A1"].alignment = center
    ws3.row_dimensions[1].height = 24

    cnt = Counter(b["customer"] for b in active if b["customer"])
    for col, h in enumerate(["排名","客戶","件數"], 1):
        c = ws3.cell(row=2, column=col, value=h)
        c.font = head_font; c.fill = head_fill; c.alignment = center; c.border = border
    for i, (name, v) in enumerate(cnt.most_common(), 1):
        for col, val in enumerate([i, name, v], 1):
            c = ws3.cell(row=2+i, column=col, value=val)
            c.alignment = center; c.border = border; c.font = Font(size=11, name="微軟正黑體")
    for col, w in enumerate([8, 20, 12], 1):
        ws3.column_dimensions[chr(64+col)].width = w

    # ── Sheet 4: 逾期 / 將到期 ─────────────────────
    ws4 = wb.create_sheet("逾期將到期")
    ws4.merge_cells("A1:F1")
    ws4["A1"] = "近 7 天將到期 + 已逾期清單"
    ws4["A1"].font = title_font; ws4["A1"].fill = title_fill; ws4["A1"].alignment = center
    ws4.row_dimensions[1].height = 24

    today_dt = datetime.today()
    items = []
    for b in active:
        if b["status"] in ("complete","已出貨","scrapped"): continue
        if not b["late_deadline"]: continue
        try:
            dd = datetime.strptime(b["late_deadline"], "%Y-%m-%d")
            days = (dd - today_dt).days
            if days <= 7: items.append((days, b))
        except: pass
    items.sort(key=lambda x: x[0])

    for col, h in enumerate(["剩餘天數","客戶","編號","規格","進貨日","最晚交期"], 1):
        c = ws4.cell(row=2, column=col, value=h)
        c.font = head_font; c.fill = head_fill; c.alignment = center; c.border = border
    for i, (days, b) in enumerate(items, 1):
        days_text = f"逾期{-days}天" if days<0 else ("今日" if days==0 else f"{days}天")
        vals = [days_text, b["customer"], b["brand_id"], spec_str(b),
                b["receipt_date"] or "", b["late_deadline"] or ""]
        for col, v in enumerate(vals, 1):
            c = ws4.cell(row=2+i, column=col, value=v)
            c.alignment = center; c.border = border
            c.font = Font(size=11, name="微軟正黑體", bold=(col==1 and days<=0))
            if days < 0:
                c.fill = PatternFill("solid", fgColor="FEE2E2")
            elif days == 0:
                c.fill = PatternFill("solid", fgColor="FEF3C7")
    for col, w in enumerate([12, 12, 14, 18, 14, 14], 1):
        ws4.column_dimensions[chr(64+col)].width = w

    # ── Sheet 5: 全部明細 ────────────────────────
    ws5 = wb.create_sheet("全部明細")
    ws5.merge_cells("A1:K1")
    ws5["A1"] = "全部鋸片明細"
    ws5["A1"].font = title_font; ws5["A1"].fill = title_fill; ws5["A1"].alignment = center
    ws5.row_dimensions[1].height = 24

    for col, h in enumerate(["年月","客戶","編號","規格","補齒","補座","反板","鋼面","進貨日","最晚交期","狀態"], 1):
        c = ws5.cell(row=2, column=col, value=h)
        c.font = head_font; c.fill = head_fill; c.alignment = center; c.border = border
    for i, b in enumerate(sorted(all_rows, key=lambda x:(x["year"] or 0, x["month"] or 0, x["customer"] or "")), 1):
        st = status_label(b)
        vals = [f"{b['year']}/{b['month']:02d}" if b['year'] else "",
                b["customer"], b["brand_id"], spec_str(b),
                b["supp_teeth"] if b["supp_teeth"] not in ("-","0") else "",
                b["supp_seats"] if b["supp_seats"] not in ("-","0") else "",
                "是" if b["fanban"]=="是" else "",
                "是" if b["steel"]=="是" else "",
                b["receipt_date"] or "", b["late_deadline"] or "", st]
        for col, v in enumerate(vals, 1):
            c = ws5.cell(row=2+i, column=col, value=v)
            c.alignment = center; c.border = border; c.font = Font(size=10, name="微軟正黑體")
    for col, w in enumerate([10, 12, 14, 16, 7, 7, 7, 7, 12, 12, 14], 1):
        ws5.column_dimensions[chr(64+col)].width = w

    out = BASE / f"儀表板總覽_{datetime.now().strftime('%y%m%d%H%M')}.xlsx"
    wb.save(out)
    return out


# ─── PPT 產生 ─────────────────────────────────────────────────
def make_ppt(folder: Path, brand_id: str, customer: str, spec: str):
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from PIL import Image as PILImg
    except ImportError:
        return None, "缺少 python-pptx 或 Pillow 套件，請執行：pip install python-pptx pillow"

    IMG_EXT = {".jpg",".jpeg",".png",".bmp",".gif",".tiff",".webp"}

    def get_imgs(folder):
        return sorted(
            [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMG_EXT],
            key=lambda x: x.name.lower()
        )

    all_imgs = get_imgs(folder)
    # Z01 = 包含 Z01/z01 的圖
    z01 = next((f for f in all_imgs if re.search(r"z01",f.stem,re.I)), None)
    # 07 以後(含) 優先
    p07 = [f for f in all_imgs if re.match(r"(0[7-9]|[1-9]\d)", f.stem)]
    # 不夠從 01-06 補
    p0106 = [f for f in all_imgs if re.match(r"0[1-6]", f.stem)]

    import random
    selected = p07[:4]
    if len(selected) < 4:
        pool = [f for f in p0106 if f not in selected]
        random.shuffle(pool)
        selected += pool[:4-len(selected)]

    if not selected and not z01:
        return None, "資料夾內沒有找到適合的照片"

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    def add_img_slide(img_path, title_text=""):
        sl = prs.slides.add_slide(blank)
        # 背景黑
        bg = sl.background.fill; bg.solid(); bg.fore_color.rgb = RGBColor(0,0,0)
        if title_text:
            tb = sl.shapes.add_textbox(Inches(0.2), Inches(0.1), Inches(12), Inches(0.5))
            tf = tb.text_frame; tf.text = title_text
            tf.paragraphs[0].runs[0].font.color.rgb = RGBColor(255,255,255)
            tf.paragraphs[0].runs[0].font.size = Pt(18)
        try:
            img = PILImg.open(img_path)
            w, h = img.size
            ratio = w/h
            max_w = 13.0; max_h = 6.8
            if ratio > max_w/max_h:
                pw = max_w; ph = pw/ratio
            else:
                ph = max_h; pw = ph*ratio
            left = (13.33-pw)/2; top = (7.5-ph)/2 + 0.4
            sl.shapes.add_picture(str(img_path), Inches(left), Inches(top), Inches(pw), Inches(ph))
        except Exception as e:
            tb = sl.shapes.add_textbox(Inches(1),Inches(2),Inches(11),Inches(3))
            tb.text_frame.text = f"無法載入圖片: {img_path.name}\n{e}"

    # 封面
    sl0 = prs.slides.add_slide(blank)
    bg = sl0.background.fill; bg.solid(); bg.fore_color.rgb = RGBColor(20,40,80)
    tb = sl0.shapes.add_textbox(Inches(1), Inches(2.5), Inches(11), Inches(2))
    tf = tb.text_frame
    tf.text = f"{customer} — {brand_id}"
    p = tf.paragraphs[0]; p.runs[0].font.size = Pt(36); p.runs[0].font.bold = True
    p.runs[0].font.color.rgb = RGBColor(255,255,255)
    tf.add_paragraph().text = spec
    tf.paragraphs[1].runs[0].font.size = Pt(22)
    tf.paragraphs[1].runs[0].font.color.rgb = RGBColor(180,210,255)

    # 照片頁
    for i, img in enumerate(selected, 1):
        add_img_slide(img, f"{'進場照片' if i==1 else '維修照片'} {i}/{len(selected)}  ·  {img.name}")

    # Z01 大圖頁
    if z01:
        add_img_slide(z01, f"大圖  {z01.name}")

    out = folder / f"{brand_id}_補齒報告.pptx"
    prs.save(str(out))
    return out, None

# ─── 主 GUI ──────────────────────────────────────────────────
class App:
    def __init__(self):
        self.cfg = load_cfg()
        self.root = tk.Tk()
        self.root.title("🪚 鋸片醫生管理系統 v8.0")
        self.root.geometry("1200x720")
        self.root.minsize(900, 580)
        self._build_ui()
        self.root.after(300, self._auto_refresh)

    # ── UI 建構 ──────────────────────────────────────────────
    def _build_ui(self):
        # 頂部工具列
        top = tk.Frame(self.root, bg="#1a3a5c", pady=6)
        top.pack(fill="x")
        tk.Label(top, text="🪚 鋸片醫生管理系統", bg="#1a3a5c", fg="white",
                 font=("Microsoft JhengHei",14,"bold")).pack(side="left", padx=12)
        self._status_lbl = tk.Label(top, text="", bg="#1a3a5c", fg="#aad4ff",
                                     font=("Microsoft JhengHei",10))
        self._status_lbl.pack(side="left", padx=8)

        for txt, cmd in [("🔄 立即掃描", self.do_scan),
                          ("📋 派工清單", self.show_dispatch),
                          ("📥 匯入對帳回傳檔", self.do_import_report),
                          ("🗓 重算進貨日", self.do_refresh_dates),
                          ("📦 歷史資料標示出貨", self.do_mark_legacy),
                          ("⚙ 設定", self.show_settings)]:
            tk.Button(top, text=txt, command=cmd, bg="#2a5f8f", fg="white",
                      relief="flat", padx=10, pady=3,
                      font=("Microsoft JhengHei",10)).pack(side="right", padx=4)

        # 主內容 - Notebook
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=6)

        self._build_tab_dashboard()
        self._build_tab_month()
        self._build_tab_customer()
        self._build_tab_log()

    # ── Tab0: 儀表板 ──────────────────────────────────────────
    def _build_tab_dashboard(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="📊 儀表板")

        # 外層捲動容器
        canvas = tk.Canvas(f, bg="#f4f6fa", highlightthickness=0)
        vs = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._dash_host = tk.Frame(canvas, bg="#f4f6fa")
        canvas.create_window((0,0), window=self._dash_host, anchor="nw")
        def _conf(e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 寬度跟著改
            canvas.itemconfig(canvas.find_all()[0], width=canvas.winfo_width())
        self._dash_host.bind("<Configure>", _conf)
        canvas.bind("<Configure>", _conf)
        # 滑鼠滾輪
        def _wheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)
        self._dash_canvas = canvas

    def _refresh_dashboard(self):
        host = self._dash_host
        for w in host.winfo_children(): w.destroy()

        # 取資料
        with get_db() as c:
            all_rows = c.execute(
                "SELECT * FROM blades WHERE status!='folder_missing'"
            ).fetchall()

        today = datetime.today().strftime("%Y-%m-%d")
        # 活動資料 = 2026/4 月(含)以後
        active = [b for b in all_rows if (b["year"] or 0) > 2026 or ((b["year"] or 0)==2026 and (b["month"] or 0)>=4)]

        total   = len(all_rows)
        act_tot = len(active)
        shipped = sum(1 for b in active if b["status"] in ("complete","已出貨"))
        okback  = sum(1 for b in active if b["ok_date"] and b["status"]=="in_progress")
        grinding= sum(1 for b in active if b["status"]=="in_progress" and not b["ok_date"])
        overdue = sum(1 for b in active
                      if b["status"]=="in_progress"
                      and b["late_deadline"] and b["late_deadline"] < today)

        # ── 標題 ──────────────────────────────────────────
        hdr = tk.Frame(host, bg="#f4f6fa"); hdr.pack(fill="x", padx=20, pady=(16,8))
        tk.Label(hdr, text="📊 鋸片醫生 · 儀表板", bg="#f4f6fa", fg="#1a3a5c",
                 font=("Microsoft JhengHei",18,"bold")).pack(side="left")
        tk.Button(hdr, text="📤 匯出 Excel", bg="#10b981", fg="white", relief="flat",
                  padx=12, pady=4, font=("Microsoft JhengHei",10),
                  command=self.do_export_dashboard).pack(side="right", padx=6)
        tk.Label(hdr, text=f"更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                 bg="#f4f6fa", fg="#666", font=("Microsoft JhengHei",9)).pack(side="right", pady=8)

        # ── KPI 卡片 ─────────────────────────────────────
        cards = tk.Frame(host, bg="#f4f6fa"); cards.pack(fill="x", padx=16, pady=6)
        kpi_data = [
            ("本月(4月起)總件數", act_tot, "#3b82f6", "📦"),
            ("研磨中", grinding, "#f59e0b", "🔧"),
            ("OK回來待出貨", okback, "#06b6d4", "🔍"),
            ("已出貨", shipped, "#10b981", "✅"),
            ("逾期件數", overdue, "#ef4444", "⚠️"),
            ("歷史總件數", total, "#6b7280", "📚"),
        ]
        for i,(label,val,color,icon) in enumerate(kpi_data):
            card = tk.Frame(cards, bg="white", bd=0, relief="flat",
                             highlightbackground="#e5e7eb", highlightthickness=1)
            card.grid(row=i//3, column=i%3, padx=6, pady=6, sticky="nsew", ipadx=4, ipady=4)
            # 左側色條
            tk.Frame(card, bg=color, width=5).pack(side="left", fill="y")
            inner = tk.Frame(card, bg="white", padx=14, pady=12); inner.pack(side="left", fill="both", expand=True)
            tk.Label(inner, text=f"{icon}  {label}", bg="white", fg="#6b7280",
                     font=("Microsoft JhengHei",10)).pack(anchor="w")
            tk.Label(inner, text=str(val), bg="white", fg=color,
                     font=("Microsoft JhengHei",24,"bold")).pack(anchor="w", pady=(4,0))
        for col in range(3): cards.columnconfigure(col, weight=1, uniform="kpi")

        # ── 雙欄區:月份分布 + 狀態分布 ───────────────────
        row2 = tk.Frame(host, bg="#f4f6fa"); row2.pack(fill="both", expand=True, padx=16, pady=(10,6))
        row2.columnconfigure(0, weight=3, uniform="r2")
        row2.columnconfigure(1, weight=2, uniform="r2")

        # (A) 月份長條圖
        left_card = self._make_card(row2, "📅 月份分布", grid=(0,0))
        self._draw_month_bars(left_card, all_rows)

        # (B) 狀態圓餅(用 canvas 畫)
        right_card = self._make_card(row2, "🎯 本月狀態分布", grid=(0,1))
        self._draw_status_pie(right_card, grinding, okback, shipped, overdue)

        # ── 客戶排行 ──────────────────────────────────────
        row3 = tk.Frame(host, bg="#f4f6fa"); row3.pack(fill="both", expand=True, padx=16, pady=(6,16))
        row3.columnconfigure(0, weight=1, uniform="r3")
        row3.columnconfigure(1, weight=1, uniform="r3")

        c_card = self._make_card(row3, "👥 本月客戶排行", grid=(0,0))
        self._draw_customer_rank(c_card, active)

        u_card = self._make_card(row3, "🚨 近7天將到期 / 已逾期", grid=(0,1))
        self._draw_urgent(u_card, active)

    def _make_card(self, parent, title, grid):
        frame = tk.Frame(parent, bg="white", highlightbackground="#e5e7eb", highlightthickness=1)
        frame.grid(row=grid[0], column=grid[1], padx=6, pady=4, sticky="nsew")
        tk.Label(frame, text=title, bg="white", fg="#1a3a5c",
                 font=("Microsoft JhengHei",12,"bold")).pack(anchor="w", padx=14, pady=(10,6))
        body = tk.Frame(frame, bg="white"); body.pack(fill="both", expand=True, padx=10, pady=(0,10))
        return body

    def _draw_month_bars(self, parent, rows):
        # 聚合 YYYY-MM
        buckets = {}
        for b in rows:
            y = b["year"]; m = b["month"]
            if not y or not m: continue
            key = f"{y}/{m:02d}"
            buckets.setdefault(key, {"done":0,"ok":0,"grind":0})
            if b["status"] in ("complete","已出貨"): buckets[key]["done"] += 1
            elif b["ok_date"] and b["status"]=="in_progress": buckets[key]["ok"] += 1
            else: buckets[key]["grind"] += 1

        keys = sorted(buckets.keys())[-12:]  # 最多 12 個月
        if not keys:
            tk.Label(parent, text="尚無資料", bg="white", fg="#999").pack(pady=20); return

        maxv = max(sum(buckets[k].values()) for k in keys) or 1
        w = 640; h = 220
        cv = tk.Canvas(parent, width=w, height=h, bg="white", highlightthickness=0)
        cv.pack(fill="x")

        pad_l, pad_r, pad_t, pad_b = 30, 10, 10, 30
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        bar_w  = plot_w / max(len(keys),1) * 0.7
        step   = plot_w / max(len(keys),1)

        # Y 軸 4 條灰線
        for i in range(5):
            y0 = pad_t + plot_h * i/4
            cv.create_line(pad_l, y0, w-pad_r, y0, fill="#e5e7eb")
            val = int(maxv*(1-i/4))
            cv.create_text(pad_l-4, y0, text=str(val), anchor="e", fill="#9ca3af",
                           font=("Microsoft JhengHei",8))

        # 堆疊長條
        COLORS = {"done":"#10b981","ok":"#06b6d4","grind":"#f59e0b"}
        for i,k in enumerate(keys):
            x = pad_l + step*i + (step-bar_w)/2
            y_bot = pad_t + plot_h
            total = sum(buckets[k].values())
            for seg in ("done","ok","grind"):
                v = buckets[k][seg]
                if not v: continue
                hh = plot_h * v / maxv
                cv.create_rectangle(x, y_bot-hh, x+bar_w, y_bot,
                                     fill=COLORS[seg], outline="")
                y_bot -= hh
            # 月份
            cv.create_text(pad_l + step*i + step/2, h-pad_b+14, text=k,
                           anchor="n", fill="#4b5563",
                           font=("Microsoft JhengHei",8))
            # 總數
            cv.create_text(pad_l + step*i + step/2, pad_t+plot_h-plot_h*total/maxv-8,
                           text=str(total), fill="#1a3a5c",
                           font=("Microsoft JhengHei",9,"bold"))

        # 圖例
        legend = tk.Frame(parent, bg="white"); legend.pack(pady=(4,0))
        for name,color,lbl in [("done","#10b981","已出貨"),
                                ("ok","#06b6d4","OK回來"),
                                ("grind","#f59e0b","研磨中")]:
            b = tk.Frame(legend, bg=color, width=14, height=14); b.pack(side="left", padx=(10,4))
            tk.Label(legend, text=lbl, bg="white", fg="#4b5563",
                     font=("Microsoft JhengHei",9)).pack(side="left")

    def _draw_status_pie(self, parent, grinding, okback, shipped, overdue):
        data = [
            ("研磨中", grinding, "#f59e0b"),
            ("OK回來", okback,  "#06b6d4"),
            ("已出貨", shipped, "#10b981"),
            ("逾期",   overdue, "#ef4444"),
        ]
        total = sum(v for _,v,_ in data)
        cv = tk.Canvas(parent, width=260, height=220, bg="white", highlightthickness=0)
        cv.pack()
        if total == 0:
            cv.create_text(130, 110, text="本月尚無資料", fill="#9ca3af",
                            font=("Microsoft JhengHei",11))
            return
        cx, cy, r = 110, 110, 80
        start = 90
        for name,val,color in data:
            if val == 0: continue
            ext = -360 * val/total
            cv.create_arc(cx-r,cy-r,cx+r,cy+r, start=start, extent=ext,
                           fill=color, outline="white", width=2)
            start += ext
        # 中間數字
        cv.create_oval(cx-38,cy-38,cx+38,cy+38, fill="white", outline="")
        cv.create_text(cx, cy-8, text=str(total), fill="#1a3a5c",
                       font=("Microsoft JhengHei",18,"bold"))
        cv.create_text(cx, cy+14, text="本月", fill="#9ca3af",
                       font=("Microsoft JhengHei",9))
        # 圖例在右側
        ly = 40
        for name,val,color in data:
            cv.create_rectangle(210, ly, 224, ly+14, fill=color, outline="")
            pct = (val/total*100) if total else 0
            cv.create_text(230, ly+7, text=f"{name} {val} ({pct:.0f}%)",
                            anchor="w", fill="#4b5563",
                            font=("Microsoft JhengHei",9))
            ly += 24

    def _draw_customer_rank(self, parent, active):
        from collections import Counter
        cnt = Counter(b["customer"] for b in active if b["customer"])
        top = cnt.most_common(8)
        if not top:
            tk.Label(parent, text="本月無資料", bg="white", fg="#9ca3af").pack(pady=10); return
        maxv = top[0][1]
        for name,v in top:
            row = tk.Frame(parent, bg="white"); row.pack(fill="x", pady=3)
            tk.Label(row, text=name, bg="white", fg="#1a3a5c", width=8, anchor="w",
                     font=("Microsoft JhengHei",10)).pack(side="left")
            bar = tk.Frame(row, bg="#e5e7eb", height=16); bar.pack(side="left", fill="x", expand=True, padx=4)
            bar.update_idletasks()
            # 用 grid 比例
            inner = tk.Frame(bar, bg="#3b82f6", height=16)
            inner.place(relwidth=v/maxv, relheight=1)
            tk.Label(row, text=str(v), bg="white", fg="#374151",
                     font=("Microsoft JhengHei",10,"bold"), width=4).pack(side="left")

    def _draw_urgent(self, parent, active):
        today = datetime.today()
        items = []
        for b in active:
            if b["status"] in ("complete","已出貨","scrapped"): continue
            if not b["late_deadline"]: continue
            try:
                dd = datetime.strptime(b["late_deadline"], "%Y-%m-%d")
                days = (dd - today).days
                if days <= 7:
                    items.append((days, b))
            except: pass
        items.sort(key=lambda x: x[0])
        if not items:
            tk.Label(parent, text="無逾期或將到期件", bg="white", fg="#10b981",
                     font=("Microsoft JhengHei",10)).pack(pady=10); return
        for days, b in items[:10]:
            row = tk.Frame(parent, bg="white"); row.pack(fill="x", pady=2)
            if days < 0:
                badge_text = f"逾期{-days}天"; color = "#ef4444"
            elif days == 0:
                badge_text = "今日"; color = "#f59e0b"
            else:
                badge_text = f"{days}天"; color = "#3b82f6"
            tk.Label(row, text=badge_text, bg=color, fg="white", width=6,
                     font=("Microsoft JhengHei",9,"bold")).pack(side="left", padx=(0,6))
            tk.Label(row, text=f"{b['customer']}  {b['brand_id']}  {spec_str(b)}",
                     bg="white", fg="#374151", anchor="w",
                     font=("Microsoft JhengHei",9)).pack(side="left", fill="x", expand=True)

    # ── Tab1: 月份 ───────────────────────────────────────────
    def _build_tab_month(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="📅 依月份")

        # 左側月份清單
        left = ttk.Frame(f, width=140); left.pack(side="left", fill="y", padx=(6,0), pady=6)
        left.pack_propagate(False)
        ttk.Label(left, text="月份", font=("Microsoft JhengHei",11,"bold")).pack(pady=4)
        self._month_lb = tk.Listbox(left, font=("Microsoft JhengHei",11), selectmode="single",
                                     activestyle="none")
        self._month_lb.pack(fill="both", expand=True)
        self._month_lb.bind("<<ListboxSelect>>", lambda e: self._load_month_detail())

        # 右側詳細
        right = ttk.Frame(f); right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self._month_info = ttk.Label(right, text="", font=("Microsoft JhengHei",11))
        self._month_info.pack(anchor="w", pady=(0,4))

        cols = ("customer","brand_id","spec","ops","receipt","early","late","ok_date","status")
        hdrs = ("客戶","編號","規格","維修工序","進貨日","最早交期","最晚交期","OK回來日","狀態")
        self._month_tv = self._make_tree(right, cols, hdrs, [80,70,160,140,90,90,90,90,110])
        self._month_tv.bind("<Double-1>", self._month_row_action)

    # ── Tab2: 客戶 ───────────────────────────────────────────
    def _build_tab_customer(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="👥 依客戶")

        # 搜尋列
        sf = ttk.Frame(f); sf.pack(fill="x", padx=6, pady=6)
        ttk.Label(sf, text="搜尋客戶:").pack(side="left")
        self._cu_var = tk.StringVar()
        ttk.Entry(sf, textvariable=self._cu_var, width=20).pack(side="left", padx=4)
        ttk.Button(sf, text="搜尋", command=self._load_customer).pack(side="left")
        ttk.Button(sf, text="全部", command=lambda:(self._cu_var.set(""),self._load_customer())).pack(side="left",padx=4)

        # 統計標籤
        self._cu_info = ttk.Label(f, text="", font=("Microsoft JhengHei",10))
        self._cu_info.pack(anchor="w", padx=6)

        cols = ("month","customer","brand_id","spec","ops","receipt","early","late","ok_date","status")
        hdrs = ("月份","客戶","編號","規格","工序","進貨日","最早交期","最晚交期","OK回來日","狀態")
        self._cu_tv = self._make_tree(f, cols, hdrs, [60,80,70,160,140,90,90,90,90,110])
        self._cu_tv.bind("<Double-1>", self._cu_row_action)

    # ── Tab3: 日誌 ───────────────────────────────────────────
    def _build_tab_log(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="📜 日誌")
        self._log_txt = ScrolledText(f, font=("Consolas",9), wrap="word")
        self._log_txt.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Button(f, text="清除", command=lambda: self._log_txt.delete("1.0","end")).pack(pady=2)

    # ── 工具 ─────────────────────────────────────────────────
    def _make_tree(self, parent, cols, hdrs, widths):
        fr = ttk.Frame(parent); fr.pack(fill="both", expand=True)
        tv = ttk.Treeview(fr, columns=cols, show="headings", selectmode="browse")
        sy = ttk.Scrollbar(fr, orient="vertical", command=tv.yview)
        sx = ttk.Scrollbar(fr, orient="horizontal", command=tv.xview)
        tv.configure(yscroll=sy.set, xscroll=sx.set)
        for c,h,w in zip(cols,hdrs,widths):
            tv.heading(c, text=h, command=lambda c=c, t=tv: self._sort_tree(t,c))
            tv.column(c, width=w, minwidth=40)
        tv.grid(row=0,column=0,sticky="nsew")
        sy.grid(row=0,column=1,sticky="ns")
        sx.grid(row=1,column=0,sticky="ew")
        fr.rowconfigure(0,weight=1); fr.columnconfigure(0,weight=1)
        # 顏色標籤
        tv.tag_configure("ok",    background="#e8f5e9")
        tv.tag_configure("overdue", background="#ffebee")
        tv.tag_configure("scrap", background="#f5f5f5", foreground="#999")
        tv.tag_configure("ok_back", background="#e3f2fd")
        return tv

    def _sort_tree(self, tv, col):
        data = [(tv.set(k,col),k) for k in tv.get_children("")]
        data.sort(reverse=getattr(tv,"_sort_rev",{}).get(col,False))
        for i,(v,k) in enumerate(data): tv.move(k,"",i)
        tv._sort_rev = getattr(tv,"_sort_rev",{})
        tv._sort_rev[col] = not tv._sort_rev.get(col,False)

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self._log_txt.insert("end", f"[{ts}] {msg}\n")
        self._log_txt.see("end")
        self._status_lbl.config(text=msg[:80])

    # ── 掃描 ─────────────────────────────────────────────────
    def do_scan(self):
        self.log("開始掃描 NAS...")
        def _run():
            n = scan_nas(self.cfg, self.log)
            self.root.after(100, self.refresh_all)
        threading.Thread(target=_run, daemon=True).start()

    def _auto_refresh(self):
        """首次啟動時自動掃描一次"""
        self.do_scan()

    def do_export_dashboard(self):
        """匯出儀表板總覽到 Excel"""
        self.log("開始匯出儀表板 Excel...")
        try:
            out = export_dashboard_excel()
        except ImportError as e:
            messagebox.showerror("缺少套件",
                f"需要安裝 openpyxl:\n{e}\n\n請執行: pip install openpyxl")
            return
        except Exception as e:
            messagebox.showerror("失敗", f"匯出失敗:\n{e}\n\n{traceback.format_exc()}")
            return
        self.log(f"✅ 已匯出: {out.name}")
        try:
            if os.name == "nt": os.startfile(str(out))
        except: pass
        messagebox.showinfo("✅ 完成", f"儀表板已匯出:\n{out}\n\n包含 5 個工作表:\n• 總覽 KPI\n• 月份分布\n• 客戶排行\n• 逾期將到期\n• 全部明細")

    def do_import_report(self):
        """匯入廠商回傳的 JSON 對帳檔,自動標記對應鋸片為已出貨"""
        fp = filedialog.askopenfilename(
            title="選擇廠商回傳的對帳檔 (.json)",
            filetypes=[("對帳回傳檔","*.json"),("所有檔案","*.*")])
        if not fp: return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                report = json.load(f)
        except Exception as e:
            messagebox.showerror("錯誤", f"無法讀取檔案:\n{e}"); return

        if report.get("type") != "sawdoctor_dispatch_report":
            messagebox.showerror("錯誤", "這不是鋸片醫生的對帳回傳檔"); return

        items = report.get("items", [])
        checked_items = [x for x in items if x.get("checked")]

        # 預覽對話框
        dlg = tk.Toplevel(self.root)
        dlg.title("匯入對帳回傳檔 — 預覽")
        dlg.geometry("680x500")

        info = (f"廠商: {report.get('vendor','未填')}\n"
                f"單號: {report.get('serial','')}\n"
                f"標題: {report.get('title','')}\n"
                f"回傳時間: {report.get('reported_at','')}\n"
                f"總件數: {report.get('total',0)}  已勾選完成: {len(checked_items)}")
        tk.Label(dlg, text=info, font=("Microsoft JhengHei",10),
                 justify="left", bg="#eff6ff", fg="#1e40af",
                 anchor="w").pack(fill="x", padx=10, pady=6)

        # 清單
        cols = ("idx","customer","brand_id","spec","action")
        hdrs = ("#","客戶","編號","規格","動作")
        tv = ttk.Treeview(dlg, columns=cols, show="headings", height=14)
        for c,h,w in zip(cols,hdrs,[40,80,80,200,200]):
            tv.heading(c, text=h); tv.column(c, width=w)
        tv.pack(fill="both", expand=True, padx=10, pady=6)

        # 比對資料庫(一筆對帳 = 可能對應多筆資料庫紀錄,因為有整合)
        match_ok = []      # [(blade_id, item, old_status), ...]
        no_match = []      # [item, ...]
        with get_db() as c:
            for x in items:
                if not x.get("checked"): continue
                # 相容新舊欄位
                folder_paths = x.get("folder_paths") or ([x.get("folder_path")] if x.get("folder_path") else [])
                brand_ids    = x.get("brand_ids") or ([x.get("brand_id")] if x.get("brand_id") else [])

                matched_rows = []
                # 1) 用 folder_path 比對(精準)
                for fp in folder_paths:
                    if not fp: continue
                    r = c.execute("SELECT id,status FROM blades WHERE folder_path=?", (fp,)).fetchone()
                    if r: matched_rows.append(r)
                # 2) 沒抓到 → 用 customer+brand_id(每個編號都查)
                if not matched_rows:
                    for bid_s in brand_ids:
                        if not bid_s: continue
                        r = c.execute(
                            "SELECT id,status FROM blades WHERE customer=? AND brand_id=? "
                            "ORDER BY id DESC LIMIT 1",
                            (x.get("customer",""), bid_s)).fetchone()
                        if r: matched_rows.append(r)

                if matched_rows:
                    for r in matched_rows:
                        match_ok.append((r["id"], x, r["status"]))
                else:
                    no_match.append(x)

        # 顯示清單
        shown_items = set()
        for bid, x, old_st in match_ok:
            if id(x) in shown_items: continue
            shown_items.add(id(x))
            cnt = x.get("count",1)
            act = "✅ 標示已出貨" if old_st not in ("complete","已出貨") else "(已是出貨狀態)"
            if cnt > 1: act = f"{act}  (含 {cnt} 片)"
            bd = x.get("brand_display") or x.get("brand_id","")
            tv.insert("", "end", values=(x["idx"], x["customer"], bd, x["spec"], act))
        for x in no_match:
            bd = x.get("brand_display") or x.get("brand_id","")
            tv.insert("", "end", values=(x["idx"], x["customer"], bd, x["spec"],
                                         "⚠ 找不到對應資料"),
                       tags=("nomatch",))
        tv.tag_configure("nomatch", background="#fee2e2")

        btns = ttk.Frame(dlg); btns.pack(fill="x", padx=10, pady=6)

        def do_apply():
            n = 0
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            rep_at = report.get("reported_at","")[:10] or now[:10]
            with get_db() as c:
                for bid, x, old_st in match_ok:
                    if old_st in ("complete","已出貨"): continue
                    c.execute(
                        "UPDATE blades SET status='已出貨',"
                        "ok_date=COALESCE(NULLIF(ok_date,''),?),"
                        "updated_at=? WHERE id=?",
                        (rep_at, now, bid))
                    n += 1
                c.commit()
            self.log(f"✅ 匯入完成:{n} 筆標示已出貨, {len(no_match)} 筆找不到對應")
            messagebox.showinfo("完成",
                f"成功匯入!\n\n"
                f"✅ 標示已出貨: {n} 筆\n"
                f"⚠ 找不到對應: {len(no_match)} 筆\n"
                f"(已略過原本就是出貨狀態的 {len(match_ok)-n} 筆)")
            dlg.destroy()
            self.refresh_all()

        ttk.Button(btns, text="✅ 確認匯入", command=do_apply, width=18).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=dlg.destroy, width=10).pack(side="left", padx=4)

    def do_mark_legacy(self):
        """將 2026/3 月(含)以前的資料一律標示為已出貨"""
        if not messagebox.askyesno("確認",
            "系統從 2026/4 月開始啟用，\n將把 2026/3 月(含)以前的資料\n全部標示為「已出貨」\n\n要繼續嗎?"):
            return
        with get_db() as c:
            cur = c.execute(
                "UPDATE blades SET status='已出貨',"
                "ok_date=COALESCE(NULLIF(ok_date,''),receipt_date),"
                "updated_at=? "
                "WHERE status!='scrapped' AND ("
                " year<2026 OR (year=2026 AND month<=3))",
                (time.strftime("%Y-%m-%d %H:%M:%S"),)
            )
            n = cur.rowcount
            c.commit()
        self.log(f"✅ 已將 {n} 筆歷史資料標示為已出貨")
        messagebox.showinfo("完成", f"已將 {n} 筆\n2026/3月(含)以前的資料\n標示為「已出貨」")
        self.refresh_all()

    def do_refresh_dates(self):
        """重新用資料夾建立時間計算進貨日 / 最早 / 最晚交期 (覆寫舊資料)"""
        if not messagebox.askyesno("確認",
            "重新依資料夾建立時間計算進貨日與交期，\n會覆蓋既有資料(狀態/OK日不受影響)\n\n要繼續嗎?"):
            return
        self.log("開始重算進貨日...")
        def _run():
            early_d = int(self.cfg.get("deadline_early",10))
            late_d  = int(self.cfg.get("deadline_late",12))
            updated = missing = 0
            with get_db() as conn:
                rows = conn.execute("SELECT id,folder_path,year,month FROM blades").fetchall()
                for r in rows:
                    fp = r["folder_path"]
                    if not fp:
                        continue
                    p = Path(fp)
                    if not p.exists():
                        missing += 1; continue
                    rd = _folder_created(p, r["year"] or datetime.today().year,
                                            r["month"] or datetime.today().month)
                    receipt = rd.strftime("%Y-%m-%d")
                    early   = add_bdays(rd, early_d).strftime("%Y-%m-%d")
                    late    = add_bdays(rd, late_d).strftime("%Y-%m-%d")
                    conn.execute("UPDATE blades SET receipt_date=?,early_deadline=?,late_deadline=?,updated_at=? WHERE id=?",
                                 (receipt, early, late, time.strftime("%Y-%m-%d %H:%M:%S"), r["id"]))
                conn.commit()
                updated = len(rows) - missing
            self.root.after(100, lambda: (
                self.log(f"✅ 重算完成: 更新 {updated} 筆, {missing} 筆資料夾消失"),
                self.refresh_all()))
        threading.Thread(target=_run, daemon=True).start()

    def refresh_all(self):
        self._refresh_dashboard()
        self._load_months()
        self._load_customer()
        self.log("畫面已更新")

    # ── 月份 Tab ─────────────────────────────────────────────
    def _load_months(self):
        with get_db() as c:
            rows = c.execute(
                "SELECT year,month,COUNT(*) as n FROM blades "
                "WHERE status!='folder_missing' "
                "GROUP BY year,month ORDER BY year DESC,month DESC"
            ).fetchall()
        self._month_lb.delete(0,"end")
        self._months_data = rows
        for r in rows:
            self._month_lb.insert("end", f"{r['year']}/{r['month']:02d}月  ({r['n']})")
        if rows: self._month_lb.selection_set(0); self._load_month_detail()

    def _load_month_detail(self):
        sel = self._month_lb.curselection()
        if not sel or not hasattr(self,"_months_data"): return
        r = self._months_data[sel[0]]
        year, month = r["year"], r["month"]
        with get_db() as c:
            blades = c.execute(
                "SELECT * FROM blades WHERE year=? AND month=? AND status!='folder_missing' "
                "ORDER BY customer,receipt_date",
                (year, month)
            ).fetchall()
        self._fill_tree(self._month_tv, blades, with_month=False)
        done = sum(1 for b in blades if b["status"] in ("complete","已出貨"))
        ok_back = sum(1 for b in blades if b["ok_date"] and b["status"]=="in_progress")
        self._month_info.config(
            text=f"{year}/{month:02d}月  共 {len(blades)} 片  |  研磨中: {len(blades)-done-ok_back}  "
                 f"OK回來: {ok_back}  已出貨: {done}")

    def _fill_tree(self, tv, blades, with_month=True):
        tv.delete(*tv.get_children())
        today = datetime.today().strftime("%Y-%m-%d")
        for b in blades:
            tag = ""
            st = b["status"]
            if st in ("complete","已出貨"): tag = "ok"
            elif st == "scrapped": tag = "scrap"
            elif b["ok_date"]: tag = "ok_back"
            elif b["late_deadline"] and b["late_deadline"] < today: tag = "overdue"

            vals = []
            if with_month: vals.append(f"{b['year']}/{b['month']:02d}")
            vals += [b["customer"], b["brand_id"], spec_str(b), ops_str(b),
                     b["receipt_date"] or "", b["early_deadline"] or "",
                     b["late_deadline"] or "", b["ok_date"] or "",
                     status_label(b)]
            tv.insert("", "end", values=vals, tags=(tag,))

    def _month_row_action(self, event):
        tv = self._month_tv
        sel = tv.selection()
        if not sel: return
        vals = tv.item(sel[0])["values"]
        # 雙擊有補齒的工單 → 問要不要產 PPT
        self._row_ppt_prompt(vals)

    def _cu_row_action(self, event):
        tv = self._cu_tv
        sel = tv.selection()
        if not sel: return
        vals = tv.item(sel[0])["values"]
        self._row_ppt_prompt(vals)

    def _row_ppt_prompt(self, vals):
        # vals 格式:月份(可選),客戶,編號,規格,...
        # 找到對應 blade
        offset = 1 if len(vals) == 10 else 0  # with_month
        customer = vals[offset]
        brand_id = vals[offset+1]
        with get_db() as c:
            b = c.execute("SELECT * FROM blades WHERE customer=? AND brand_id=?",
                          (customer, brand_id)).fetchone()
        if not b: return
        st = b["supp_teeth"]
        has_supp = st and st not in ("-","0","")
        actions = ["開啟資料夾"]
        if has_supp: actions.insert(0, f"產生補齒 PPT (補{st}齒)")
        if b["ok_date"] or b["status"] in ("complete","已出貨"):
            actions.append("標記已出貨")
        dlg = tk.Toplevel(self.root)
        dlg.title(f"{customer} — {brand_id}")
        dlg.geometry("320x200")
        ttk.Label(dlg, text=f"{customer}  {brand_id}\n{spec_str(b)}\n工序: {ops_str(b)}\n狀態: {status_label(b)}",
                  font=("Microsoft JhengHei",10)).pack(pady=10)
        for act in actions:
            ttk.Button(dlg, text=act, width=28,
                       command=lambda a=act,blade=b,d=dlg: self._do_action(a,blade,d)).pack(pady=2)
        ttk.Button(dlg, text="關閉", command=dlg.destroy).pack(pady=4)

    def _do_action(self, action, b, dlg):
        dlg.destroy()
        fp = b["folder_path"]
        if "開啟資料夾" in action:
            if fp and Path(fp).exists():
                if os.name=="nt": os.startfile(fp)
            else: messagebox.showwarning("警告", f"資料夾不存在:\n{fp}")
        elif "PPT" in action:
            folder = Path(fp) if fp else None
            if not folder or not folder.exists():
                messagebox.showerror("錯誤","資料夾不存在")
                return
            out, err = make_ppt(folder, b["brand_id"], b["customer"], spec_str(b))
            if err:
                messagebox.showerror("PPT 失敗", err)
            else:
                messagebox.showinfo("✅ 完成", f"PPT 已產生:\n{out}")
                try:
                    if os.name=="nt": os.startfile(str(out))
                except: pass
        elif "已出貨" in action:
            with get_db() as c:
                c.execute("UPDATE blades SET status='已出貨',updated_at=? WHERE id=?",
                           (time.strftime("%Y-%m-%d %H:%M:%S"), b["id"]))
                c.commit()
            self.refresh_all()

    # ── 客戶 Tab ─────────────────────────────────────────────
    def _load_customer(self):
        q = self._cu_var.get().strip()
        sql = "SELECT * FROM blades WHERE status!='folder_missing'"
        args = []
        if q:
            sql += " AND (customer LIKE ? OR brand_id LIKE ?)"
            args = [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY year DESC,month DESC,customer,receipt_date"
        with get_db() as c:
            blades = c.execute(sql, args).fetchall()
        self._fill_tree(self._cu_tv, blades, with_month=True)
        done = sum(1 for b in blades if b["status"] in ("complete","已出貨"))
        ok_b = sum(1 for b in blades if b["ok_date"] and b["status"]=="in_progress")
        self._cu_info.config(
            text=f"共 {len(blades)} 筆  |  研磨中: {len(blades)-done-ok_b}  "
                 f"🔵 OK回來待出貨: {ok_b}  ✅ 已出貨: {done}")

    # ── 派工清單 ─────────────────────────────────────────────
    def show_dispatch(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("派工清單設定"); dlg.geometry("500x560")

        ttk.Label(dlg, text="月份範圍:", font=("Microsoft JhengHei",10,"bold")).pack(pady=(12,4))
        range_var = tk.StringVar(value="單一月份")
        rng_box = ttk.Combobox(dlg, textvariable=range_var, state="readonly", width=30,
                               values=["單一月份","跨 2 個月 (本月 + 上個月)",
                                       "跨 2 個月 (本月 + 下個月)","自訂兩個月"])
        rng_box.pack()

        # 主月份
        frm1 = tk.Frame(dlg); frm1.pack(pady=(8,2))
        ttk.Label(frm1, text="月份 1:").pack(side="left", padx=4)
        mon_var = tk.StringVar(value=datetime.now().strftime("%Y-%m"))
        ttk.Entry(frm1, textvariable=mon_var, width=12,
                  font=("Microsoft JhengHei",10)).pack(side="left")

        # 第二個月份(自訂時用)
        frm2 = tk.Frame(dlg)
        ttk.Label(frm2, text="月份 2:").pack(side="left", padx=4)
        mon2_var = tk.StringVar(value="")
        ttk.Entry(frm2, textvariable=mon2_var, width=12,
                  font=("Microsoft JhengHei",10)).pack(side="left")

        def on_range_change(*_):
            if range_var.get() == "自訂兩個月":
                frm2.pack(pady=(2,4))
            else:
                frm2.pack_forget()
        range_var.trace_add("write", on_range_change)

        ttk.Label(dlg, text="篩選狀態:").pack(pady=(10,4))
        st_var = tk.StringVar(value="未完成 (研磨中+OK回來)")
        ttk.Combobox(dlg, textvariable=st_var,
                     values=["未完成 (研磨中+OK回來)","研磨中","OK回來","已出貨","全部 (含已出貨,排除報廢)"],
                     state="readonly", width=32).pack()

        # 是否包含已報廢
        scrap_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dlg, text="包含已報廢的鋸片", variable=scrap_var).pack(pady=(10,4))

        ttk.Label(dlg, text="輸出格式:").pack(pady=(10,4))
        fmt_var = tk.StringVar(value="HTML (廠商對帳)")
        ttk.Combobox(dlg, textvariable=fmt_var,
                     values=["HTML (廠商對帳)","Excel (.xlsx)","Word (.docx)",
                             "客戶維修報價明細 Excel"],
                     state="readonly", width=32).pack()

        quote_customer_var = tk.StringVar()
        quote_customer_box = ttk.Combobox(dlg, textvariable=quote_customer_var,
                                          state="disabled", width=32)
        quote_customer_label = ttk.Label(dlg, text="客戶（報價明細限定一位）:")

        def parse_ym(s):
            """字串 YYYY-MM 轉 (y,m),失敗回傳 None"""
            try:
                y, m = map(int, s.strip().split("-"))
                if 1 <= m <= 12: return (y, m)
            except: pass
            return None

        def shift_month(y, m, delta):
            """月份加減,回傳 (y,m)"""
            idx = y*12 + (m-1) + delta
            return (idx//12, idx%12 + 1)

        def selected_rows(show_error=False):
            ym1 = parse_ym(mon_var.get() or datetime.now().strftime("%Y-%m"))
            if not ym1:
                if show_error: messagebox.showerror("錯誤", "月份 1 格式應為 YYYY-MM")
                return None, []
            y1, m1 = ym1
            mode = range_var.get()
            ym2 = None
            if mode == "跨 2 個月 (本月 + 上個月)": ym2 = shift_month(y1, m1, -1)
            elif mode == "跨 2 個月 (本月 + 下個月)": ym2 = shift_month(y1, m1, +1)
            elif mode == "自訂兩個月":
                ym2 = parse_ym(mon2_var.get())
                if not ym2 or ym2 == ym1:
                    if show_error: messagebox.showerror("錯誤", "月份 2 格式應為 YYYY-MM，且不可與月份 1 相同")
                    return None, []
            months = [ym1] if ym2 is None else sorted([ym1, ym2])
            with get_db() as c:
                rows = []
                for y, m in months:
                    rows.extend(c.execute(
                        "SELECT * FROM blades WHERE year=? AND month=? AND status!='folder_missing' ORDER BY customer,receipt_date",
                        (y, m)).fetchall())
            if not scrap_var.get(): rows = [b for b in rows if b["status"] != "scrapped"]
            st = st_var.get()
            if st.startswith("未完成"): rows = [b for b in rows if b["status"] == "in_progress"]
            elif st == "研磨中": rows = [b for b in rows if b["status"] == "in_progress" and not b["ok_date"]]
            elif st == "OK回來": rows = [b for b in rows if b["ok_date"] and b["status"] == "in_progress"]
            elif st == "已出貨": rows = [b for b in rows if b["status"] in ("complete", "已出貨")]
            return months, rows

        def refresh_quote_customers(*_):
            is_quote = fmt_var.get() == "客戶維修報價明細 Excel"
            if not is_quote:
                quote_customer_label.pack_forget(); quote_customer_box.pack_forget(); return
            quote_customer_label.pack(pady=(10, 4)); quote_customer_box.pack()
            months, rows = selected_rows()
            customers = sorted({str(b["customer"]).strip() for b in rows
                                if b["status"] not in ("folder_missing", "scrapped") and str(b["customer"]).strip()})
            quote_customer_box.configure(values=customers, state="readonly")
            if quote_customer_var.get() not in customers:
                quote_customer_var.set(customers[0] if len(customers) == 1 else "")
        fmt_var.trace_add("write", refresh_quote_customers)
        for watched in (range_var, mon_var, mon2_var, st_var, scrap_var):
            watched.trace_add("write", refresh_quote_customers)

        def gen():
            months, rows = selected_rows(show_error=True)
            if months is None: return

            if not rows:
                messagebox.showinfo("提示","符合條件的資料為 0 筆"); return

            # 跨月份時,依進貨日重新排序
            if len(months) > 1:
                rows = sorted(rows, key=lambda b: (b["customer"] or "", b["receipt_date"] or ""))

            # 標題
            if len(months) == 1:
                y, m = months[0]
                title = f"{y}/{m:02d}月 派工清單"
            else:
                (ya, ma), (yb, mb) = months
                title = f"{ya}/{ma:02d} ~ {yb}/{mb:02d}月 跨月派工清單"

            fmt = fmt_var.get()
            if fmt == "客戶維修報價明細 Excel":
                customer = quote_customer_var.get().strip()
                if not customer:
                    messagebox.showerror("錯誤", "客戶維修報價明細必須選擇一位客戶"); return
                quote_rows = [b for b in rows if b["customer"] == customer and b["status"] not in ("folder_missing", "scrapped")]
                if not quote_rows:
                    messagebox.showerror("錯誤", "所選客戶沒有可列入報價的鋸片"); return
                self.show_quote_confirmation(quote_rows, customer, months)
                return
            dlg.destroy()
            try:
                if fmt.startswith("HTML"):
                    p = gen_dispatch_html(rows, title)
                    webbrowser.open(p.as_uri())
                elif fmt.startswith("Excel"):
                    p = export_dispatch_excel(rows, title)
                    if os.name == "nt": os.startfile(str(p))
                    self.log(f"✅ Excel 已輸出: {p.name}")
                elif fmt.startswith("Word"):
                    p = export_dispatch_word(rows, title)
                    if os.name == "nt": os.startfile(str(p))
                    self.log(f"✅ Word 已輸出: {p.name}")
            except ImportError as e:
                messagebox.showerror("缺少套件",
                    f"需要安裝額外套件:\n{e}\n\n"
                    "請執行: pip install openpyxl python-docx")
            except Exception as e:
                messagebox.showerror("失敗", f"產生失敗:\n{e}")

        ttk.Button(dlg, text="✅ 產生並開啟", command=gen, width=20).pack(pady=18)

    def show_quote_confirmation(self, rows, customer, months):
        """人工確認報價草稿；所有調整只存在於本次快照，不回寫鋸片資料。"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"客戶維修報價確認：{customer}")
        dialog.geometry("1180x650")
        dialog.transient(self.root)

        quote_date = date.today()
        with get_db() as conn:
            rules = load_effective_price_rules(conn, quote_date)
        base_lines = [
            (quote_line_from_blade(row, rules), manual_only_repair_labels(row))
            for row in rows
        ]
        state_rows = []

        ttk.Label(dialog, text=f"客戶：{customer}　月份：{_quote_month_range(months)}　未稅",
                  font=("Microsoft JhengHei", 12, "bold")).pack(pady=(10, 4))
        ttk.Label(dialog, text="可調整數量、單價與備註；紅色『待人工填價』未完成前不能產生 Excel。",
                  foreground="#a00000").pack(pady=(0, 8))

        canvas = tk.Canvas(dialog, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas)
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        scrollbar.pack(side="right", fill="y", padx=(0, 10))

        headers = ["列入", "編號 / 規格 / 原工序", "研磨\n數量", "研磨\n單價", "補齒\n數量", "補齒\n單價", "反板\n數量", "反板\n單價", "小計", "備註 / 狀態"]
        for column, header in enumerate(headers):
            ttk.Label(content, text=header, anchor="center", relief="solid", padding=4).grid(
                row=0, column=column, sticky="nsew")
        for column, width in enumerate((6, 35, 7, 8, 7, 8, 7, 8, 10, 25)):
            content.columnconfigure(column, minsize=width * 7)

        total_var = tk.StringVar(value="未稅總計：NT$ 0")
        confirm_button = ttk.Button(dialog, text="產生客戶維修報價明細 Excel")

        def make_line(item):
            try:
                line = apply_manual_quote(
                    item["base"], included=item["included"].get(),
                    grinding_qty=item["grinding_qty"].get(), grinding_unit=item["grinding_unit"].get(),
                    tooth_qty=item["tooth_qty"].get(), tooth_unit=item["tooth_unit"].get(),
                    fanban_qty=item["fanban_qty"].get(), fanban_unit=item["fanban_unit"].get(),
                    note=item["note"].get(),
                )
                return quote_line_with_manual_confirmation(line, item["manual_labels"])
            except ValueError:
                return None

        def refresh():
            total = 0; all_valid = False
            any_included = False
            for item in state_rows:
                line = make_line(item)
                included = item["included"].get()
                validation_error = "待人工填價" if line is None else quote_line_validation_error(
                    line, item["manual_labels"]
                )
                valid = not validation_error
                if line is not None and included and valid:
                    any_included = True
                    total += line.subtotal
                item["draft"] = line
                item["subtotal"].set(f"NT$ {line.subtotal:,}" if line and included else "—")
                item["status"].set("可產生" if valid or not included else validation_error)
                item["status_label"].configure(foreground="#006400" if valid or not included else "#b00000")
                if included and not valid: all_valid = False
                elif included and valid: all_valid = True if not any_included else all_valid
            # all included rows must be valid, and at least one must remain included.
            all_valid = any_included and all(
                (not item["included"].get()) or (
                    item["draft"] is not None and item["status"].get() == "可產生"
                ) for item in state_rows
            )
            total_var.set(f"未稅總計：NT$ {total:,}")
            confirm_button.configure(state="normal" if all_valid else "disabled")

        for row_number, (line, manual_labels) in enumerate(base_lines, start=1):
            item = {
                "base": line, "included": tk.BooleanVar(value=True),
                "grinding_qty": tk.StringVar(value=str(line.grinding_qty)),
                "grinding_unit": tk.StringVar(value=str(line.grinding_unit)),
                "tooth_qty": tk.StringVar(value=str(line.tooth_qty)),
                "tooth_unit": tk.StringVar(value=str(line.tooth_unit)),
                "fanban_qty": tk.StringVar(value=str(line.fanban_qty)),
                "fanban_unit": tk.StringVar(value=str(line.fanban_unit)),
                "note": tk.StringVar(value=line.note), "subtotal": tk.StringVar(), "status": tk.StringVar(),
                "manual_labels": manual_labels,
            }
            ttk.Checkbutton(content, variable=item["included"], command=refresh).grid(row=row_number, column=0, sticky="nsew", padx=2, pady=2)
            source = f"{line.brand_id}\n{line.spec}\n原：研磨 {line.source_grind}／補齒 {line.source_supp_teeth}／反板 {line.source_fanban}"
            if manual_labels:
                source += "\n待人工確認：" + "、".join(manual_labels)
            ttk.Label(content, text=source, justify="left", anchor="w", relief="solid", padding=3).grid(row=row_number, column=1, sticky="nsew", padx=1, pady=1)
            for column, key in enumerate(("grinding_qty", "grinding_unit", "tooth_qty", "tooth_unit", "fanban_qty", "fanban_unit"), start=2):
                entry = ttk.Entry(content, textvariable=item[key], width=8, justify="center")
                entry.grid(row=row_number, column=column, sticky="nsew", padx=1, pady=1)
                item[key].trace_add("write", lambda *_: refresh())
            ttk.Label(content, textvariable=item["subtotal"], anchor="e", relief="solid", padding=3).grid(row=row_number, column=8, sticky="nsew", padx=1, pady=1)
            right = ttk.Frame(content); right.grid(row=row_number, column=9, sticky="nsew", padx=1, pady=1)
            ttk.Entry(right, textvariable=item["note"], width=22).pack(fill="x")
            item["note"].trace_add("write", lambda *_: refresh())
            item["status_label"] = ttk.Label(right, textvariable=item["status"])
            item["status_label"].pack(anchor="w")
            state_rows.append(item)

        footer = ttk.Frame(dialog); footer.pack(fill="x", padx=12, pady=10)
        ttk.Label(footer, textvariable=total_var, font=("Microsoft JhengHei", 12, "bold")).pack(side="left")

        def confirm():
            refresh()
            included = [item["draft"] for item in state_rows if item["included"].get()]
            if not included or any(line is None for line in included) or confirm_button.instate(["disabled"]):
                messagebox.showerror("待人工填價", "請先完成所有列入鋸片的數量與單價。", parent=dialog); return
            if any(line.customer != customer for line in included):
                messagebox.showerror("資料錯誤", "報價明細不得混用不同客戶。", parent=dialog); return
            output_dir = BASE / "客戶維修報價"
            try:
                with get_db() as conn:
                    _batch, outputs = save_and_export_customer_quote(
                        conn, output_dir, customer, months, included, "鋸片醫生",
                        quote_date=quote_date,
                    )
                output = outputs.get("xlsx") or outputs.get("pdf")
                if os.name == "nt" and hasattr(os, "startfile"): os.startfile(str(output))
                self.log(f"✅ 客戶維修報價明細已輸出: {output.name}")
                dialog.destroy()
            except ImportError as error:
                messagebox.showerror("缺少套件", f"需要安裝 openpyxl：\n{error}", parent=dialog)
            except Exception as error:
                messagebox.showerror("產生失敗", str(error), parent=dialog)

        confirm_button.configure(command=confirm)
        confirm_button.pack(in_=footer, side="right")
        refresh()

    # ── 設定 ─────────────────────────────────────────────────
    def show_settings(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("設定"); dlg.geometry("680x200")
        fields = [
            ("NAS 掃描路徑", "scan_root", 60),
            ("最早交期(工作天)", "deadline_early", 6),
            ("最晚交期(工作天)", "deadline_late", 6),
        ]
        entries = {}
        for i,(label,key,w) in enumerate(fields):
            ttk.Label(dlg, text=label).grid(row=i, column=0, sticky="w", padx=10, pady=8)
            e = ttk.Entry(dlg, width=w)
            e.insert(0, str(self.cfg.get(key,"")))
            e.grid(row=i, column=1, padx=6, sticky="we")
            entries[key] = e
        dlg.columnconfigure(1, weight=1)

        def save():
            for k,e in entries.items():
                v = e.get().strip()
                if k in ("deadline_early","deadline_late"):
                    try: v = int(v)
                    except: messagebox.showerror("錯誤",f"{k} 必須是整數"); return
                self.cfg[k] = v
            save_cfg(self.cfg)
            messagebox.showinfo("完成","設定已儲存\n下次掃描生效")
            dlg.destroy()

        ttk.Button(dlg, text="儲存", command=save).grid(row=len(fields), column=1, sticky="e", padx=10, pady=8)

    # ── 啟動 ─────────────────────────────────────────────────
    def run(self):
        self.root.mainloop()


# ─── 進入點 ──────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        app = App()
        app.run()
    except Exception:
        err = traceback.format_exc()
        try:
            import tkinter.messagebox as mb
            mb.showerror("啟動失敗", err)
        except:
            print(err)
        with open(BASE/"crash.log","a",encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{err}\n")
