"""Session state management wrapper for Streamlit."""

import atexit
import copy
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st
import pandas as pd

from core.state_machine import StateMachine, WorkflowState, WorkflowType

# 고아 스냅샷 디렉토리 자동 정리 (앱 시작 시 1회 실행)
_SNAPSHOT_MAX_AGE_HOURS = 24

def _cleanup_stale_snapshots() -> None:
    """tmp에 남아있는 오래된 agent_snapshots_* 디렉토리 삭제"""
    tmp = Path(tempfile.gettempdir())
    cutoff = time.time() - (_SNAPSHOT_MAX_AGE_HOURS * 3600)
    for d in tmp.glob("agent_snapshots_*"):
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)

_cleanup_stale_snapshots()


@dataclass
class SessionSnapshot:
    """특정 시점의 세션 상태 스냅샷 (DataFrame은 디스크에 parquet로 저장)"""
    state: WorkflowState
    workflow_type: WorkflowType
    metadata: dict
    context_keys: list[str]           # workflow_context에 있던 DataFrame 키 목록
    disk_dir: Path                    # parquet 파일이 저장된 디렉토리
    chat_history_length: int
    state_history: list[WorkflowState]

    def load_context(self) -> dict[str, pd.DataFrame]:
        """디스크에서 DataFrame들을 읽어 반환"""
        result = {}
        for key in self.context_keys:
            path = self.disk_dir / f"{key}.parquet"
            if path.exists():
                result[key] = pd.read_parquet(path)
        return result

    def cleanup(self) -> None:
        """디스크의 parquet 파일 삭제"""
        if self.disk_dir.exists():
            shutil.rmtree(self.disk_dir, ignore_errors=True)


class SessionManager:
    """Wraps st.session_state for typed access."""

    def __init__(self):
        if "initialized" not in st.session_state:
            self._initialize()
        # 기존 세션 호환: snapshots 키가 없으면 추가
        if "snapshots" not in st.session_state:
            st.session_state.snapshots = {}
        if "snapshot_base_dir" not in st.session_state:
            tmp_dir = tempfile.TemporaryDirectory(prefix="agent_snapshots_")
            st.session_state.snapshot_tmp_handle = tmp_dir
            st.session_state.snapshot_base_dir = Path(tmp_dir.name)
            atexit.register(lambda: shutil.rmtree(tmp_dir.name, ignore_errors=True))

    def _initialize(self) -> None:
        st.session_state.initialized = True
        st.session_state.state_machine = StateMachine()
        st.session_state.chat_history = []
        st.session_state.workflow_context = {}  # str -> DataFrame
        st.session_state.current_product = None
        st.session_state.metadata = {}
        st.session_state.snapshots = {}  # state.name -> SessionSnapshot
        # TemporaryDirectory: GC 또는 프로세스 종료 시 자동 삭제
        tmp_dir = tempfile.TemporaryDirectory(prefix="agent_snapshots_")
        st.session_state.snapshot_tmp_handle = tmp_dir  # reference 유지 (GC 방지)
        st.session_state.snapshot_base_dir = Path(tmp_dir.name)
        atexit.register(lambda: shutil.rmtree(tmp_dir.name, ignore_errors=True))

    @property
    def state_machine(self) -> StateMachine:
        return st.session_state.state_machine

    @property
    def current_state(self) -> WorkflowState:
        return self.state_machine.state

    @property
    def chat_history(self) -> list[dict[str, str]]:
        return st.session_state.chat_history

    def add_message(self, role: str, content: str) -> None:
        st.session_state.chat_history.append({"role": role, "content": content})

    def get_dataframe(self, key: str) -> pd.DataFrame | None:
        return st.session_state.workflow_context.get(key)

    def set_dataframe(self, key: str, df: pd.DataFrame) -> None:
        st.session_state.workflow_context[key] = df

    def set_metadata(self, key: str, value: Any) -> None:
        st.session_state.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return st.session_state.metadata.get(key, default)

    def save_snapshot(self) -> None:
        """현재 상태의 스냅샷을 저장. DataFrame은 디스크에 parquet로 기록."""
        sm = self.state_machine
        state_name = sm.state.name

        # 기존 스냅샷이 있으면 디스크 정리
        old = st.session_state.snapshots.get(state_name)
        if old is not None:
            old.cleanup()

        # DataFrame을 디스크에 저장
        disk_dir = st.session_state.snapshot_base_dir / state_name
        disk_dir.mkdir(parents=True, exist_ok=True)

        context = st.session_state.workflow_context
        context_keys = []
        for key, df in context.items():
            df.to_parquet(disk_dir / f"{key}.parquet", index=False)
            context_keys.append(key)

        snapshot = SessionSnapshot(
            state=sm.state,
            workflow_type=sm.workflow_type,
            metadata=copy.deepcopy(st.session_state.metadata),
            context_keys=context_keys,
            disk_dir=disk_dir,
            chat_history_length=len(st.session_state.chat_history),
            state_history=list(sm.history),
        )
        st.session_state.snapshots[state_name] = snapshot

    def restore_snapshot(self, target_state: WorkflowState) -> bool:
        """스냅샷에서 metadata, workflow_context, history 복원.
        chat_history를 스냅샷 시점까지 잘라내고 롤백 안내 메시지 추가.
        target 이후 스냅샷 삭제."""
        snapshots: dict[str, SessionSnapshot] = st.session_state.snapshots
        snapshot = snapshots.get(target_state.name)
        if snapshot is None:
            return False

        # metadata 복원
        st.session_state.metadata = copy.deepcopy(snapshot.metadata)

        # workflow_context를 디스크에서 복원
        st.session_state.workflow_context = snapshot.load_context()

        # state_machine 롤백
        sm = self.state_machine
        sm._history = list(snapshot.state_history)
        sm._state = target_state

        # chat_history를 스냅샷 시점까지 잘라냄
        st.session_state.chat_history = st.session_state.chat_history[:snapshot.chat_history_length]

        # 롤백 안내 메시지 추가
        from ui.chat import STATE_LABELS
        label = STATE_LABELS.get(target_state.name, target_state.name)
        self.add_message("assistant", f"**[{label}]** 단계로 롤백했습니다. 이 단계부터 다시 진행합니다.")

        # target 이후 스냅샷 삭제 (디스크 정리 포함)
        from ui.chat import SIDEBAR_STAGES
        target_idx = SIDEBAR_STAGES.index(target_state) if target_state in SIDEBAR_STAGES else -1
        if target_idx >= 0:
            for stage in SIDEBAR_STAGES[target_idx + 1:]:
                removed = snapshots.pop(stage.name, None)
                if removed is not None:
                    removed.cleanup()

        return True

    def get_completed_states(self) -> list[WorkflowState]:
        """스냅샷이 존재하는 상태 목록 반환 (= 롤백 가능 상태)"""
        return [
            WorkflowState[name] for name in st.session_state.snapshots
            if name in WorkflowState.__members__
        ]

    def reset(self) -> None:
        # TemporaryDirectory 정리 (디스크 전체 삭제)
        tmp_handle = st.session_state.get("snapshot_tmp_handle")
        if tmp_handle is not None:
            tmp_handle.cleanup()
        st.session_state.clear()
        self._initialize()
