"""State global aplikasi: folder bukti aktif + workspace otomatis."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QSettings, Signal

from ..forensic import fconfig
from ..forensic.store import CaseStore
from ..workspace import validate_evidence_dir, workspace_for


class AppState(QObject):
    evidence_changed = Signal()
    data_changed = Signal()      # isi DB berubah (ekstraksi/verifikasi/amankan)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.evidence_dir: Optional[str] = None
        self.workspace: Optional[Path] = None
        self.store: Optional[CaseStore] = None

    def set_evidence(self, folder: str) -> Optional[str]:
        err = validate_evidence_dir(folder)
        if err:
            return err
        if self.store:
            self.store.close()
        ev = str(Path(folder).resolve())
        self.evidence_dir = ev
        self.workspace = workspace_for(ev)
        self.store = CaseStore(self.workspace)
        self.store.init_workspace(ev)
        QSettings("CyberForensic", "EvidenceSearch").setValue("last_evidence", ev)
        self.evidence_changed.emit()
        self.data_changed.emit()
        return None

    def last_evidence(self) -> str:
        return str(QSettings("CyberForensic", "EvidenceSearch").value("last_evidence", "") or "")

    def reader(self) -> Optional[sqlite3.Connection]:
        """Koneksi read-only terpisah untuk tampilan (aman saat ekstraksi berjalan)."""
        if not self.workspace:
            return None
        db = self.workspace / fconfig.CASE_DB
        if not db.exists():
            return None
        return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30, check_same_thread=False)

    def close(self) -> None:
        if self.store:
            self.store.close()
