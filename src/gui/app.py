"""
Shiny Hunter FRLG / BDSP — Streamlit GUI
Run with: python -m streamlit run src/gui/app.py
"""

import sys
import queue
import threading
import logging
import time
import cv2
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.capture.capture_handler import CaptureHandler
from src.detection.shiny_detector import ShinyDetector
from src.controller.switch_controller import SwitchController, ControllerMode
from src.automation.sequences import HuntSequence, BDSPHuntSequence, BDSP_TARGETS
from src.licensing.license_manager import HUNT_CATALOGUE, get_unlocked_hunts, activate_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Thread-safe log queue — background thread writes here, main thread reads
# ---------------------------------------------------------------------------
_log_queue: queue.Queue = queue.Queue()

# ---------------------------------------------------------------------------
# Page config (called ONCE at the top — Streamlit requires this)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="✨ Shiny Hunter FRLG",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "running":      False,
    "encounters":   0,
    "shiny_found":  False,
    "log_messages": [],
    "start_time":   None,
    "hunt_thread":  None,
    "sequence":     None,
    "last_frame":   None,
    "activate_msg": None,
    "activate_ok":  None,
    "page":         "Hunt",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    path = PROJECT_ROOT / "config" / "settings.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def flush_log_queue():
    """Drain thread-safe queue into session_state.log_messages. Call on every rerun."""
    while not _log_queue.empty():
        try:
            msg = _log_queue.get_nowait()
            st.session_state.log_messages.append(msg)
        except queue.Empty:
            break
    if len(st.session_state.log_messages) > 200:
        st.session_state.log_messages = st.session_state.log_messages[-200:]


def add_log(msg: str):
    """Thread-safe log: safe to call from any thread."""
    ts = datetime.now().strftime("%H:%M:%S")
    _log_queue.put(f"[{ts}] {msg}")
    logging.info(msg)


def run_hunt_thread(capture_idx: int, hunt_id: str, ctrl_mode: str, serial_port: str):
    """Runs in a background daemon thread. hunt_id is always the catalogue key e.g. 'arceus'."""
    try:
        mode = (ControllerMode.SERIAL
                if "Serial" in ctrl_mode
                else ControllerMode.KEYBOARD)

        capture    = CaptureHandler(device_index=capture_idx)
        detector   = ShinyDetector()
        controller = SwitchController(mode=mode, port=serial_port)

        if hunt_id in BDSP_TARGETS:
            sequence = BDSPHuntSequence(
                target=hunt_id,
                controller=controller,
                capture=capture,
                on_status=add_log,
                on_encounter=_on_encounter,
                on_progress=_on_progress,
            )
        else:
            sequence = HuntSequence(
                target=hunt_id,
                controller=controller,
                detector=detector,
                capture=capture,
                on_status=add_log,
                on_encounter=_on_encounter,
                on_progress=_on_progress,
            )

        # Store reference so Stop button can call sequence.stop()
        _log_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] Sequence created for {hunt_id}")
        # Can't use st.session_state from thread safely for writes, use a module-level ref
        _current_sequence[0] = sequence

        capture.open()
        controller.connect()
        try:
            result = sequence.run()
            if result.is_shiny:
                add_log(f"🌟 SHINY {hunt_id.upper()} found after {result.encounters} encounters!")
                _shared_state["shiny_found"] = True
                _shared_state["last_frame"]  = result.frame
        finally:
            capture.close()
            controller.disconnect()

    except Exception as exc:
        add_log(f"ERROR: {exc}")
        logging.exception("Hunt thread crashed")
    finally:
        _shared_state["running"] = False


# Shared dict for thread → main thread communication (avoids session_state from threads)
_shared_state: dict = {"running": False, "shiny_found": False, "last_frame": None,
                        "encounters": 0}
_current_sequence: list = [None]   # [0] = current HuntSequence or BDSPHuntSequence


def _on_encounter(count: int, is_shiny: bool):
    _shared_state["encounters"] = count
    if is_shiny:
        _shared_state["shiny_found"] = True


def _on_progress(target: str, count: int):
    _shared_state["encounters"] = count


def sync_shared_state():
    """Pull thread-written values into session_state on each rerun."""
    st.session_state.encounters  = _shared_state["encounters"]
    st.session_state.running     = _shared_state["running"]
    if _shared_state["shiny_found"]:
        st.session_state.shiny_found = True
    if _shared_state["last_frame"] is not None:
        st.session_state.last_frame = _shared_state["last_frame"]


# ---------------------------------------------------------------------------
# Build display_name → hunt_id reverse map
# ---------------------------------------------------------------------------
_DISPLAY_TO_ID = {v["display"]: k for k, v in HUNT_CATALOGUE.items()}

# ---------------------------------------------------------------------------
# Sidebar — page navigation (always visible)
# ---------------------------------------------------------------------------
flush_log_queue()
sync_shared_state()

with st.sidebar:
    st.markdown("## ✨ Shiny Hunter")
    page = st.radio(
        "Navigate",
        options=["Hunt", "Store"],
        index=["Hunt", "Store"].index(st.session_state.page),
        label_visibility="collapsed",
        key="nav_radio",
    )
    st.session_state.page = page
    st.divider()

# ===========================================================================
# PAGE: STORE
# ===========================================================================
if st.session_state.page == "Store":
    st.title("🛒 Unlock a Hunt")
    st.markdown(
        "Each legendary Pokémon hunt is sold separately. "
        "Purchase on **itch.io**, receive your license key by email, "
        "then paste it below to unlock instantly."
    )

    unlocked = get_unlocked_hunts()
    cols = st.columns(min(len(HUNT_CATALOGUE), 4))
    for i, (hunt_id, info) in enumerate(HUNT_CATALOGUE.items()):
        col = cols[i % len(cols)]
        with col:
            locked = hunt_id not in unlocked
            badge  = "🔒 Locked" if locked else "✅ Unlocked"
            color  = info["color"]
            price  = info["price"] if locked else "Owned"
            st.markdown(
                f"""
                <div style="
                    border: 2px solid {color};
                    border-radius: 12px;
                    padding: 20px 16px;
                    text-align: center;
                    margin-bottom: 12px;
                    background: {'#1a1a2e' if locked else '#0f3460'};
                ">
                    <div style="font-size: 2.5rem;">{'❓' if locked else '⭐'}</div>
                    <div style="font-size: 1.2rem; font-weight: bold; color: {color}; margin: 8px 0;">
                        {info['display']}
                    </div>
                    <div style="color: #aaa; font-size: 0.9rem;">{badge}</div>
                    <div style="font-weight: bold; margin-top: 8px; color: white;">{price}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()
    st.subheader("🔑 Activate a License Key")
    with st.form("activate_form"):
        key_input = st.text_input(
            "License Key",
            placeholder="LUGIA-XXXXXX-XXXX",
            label_visibility="collapsed",
            key="key_input",
        )
        submitted = st.form_submit_button("Activate", type="primary", use_container_width=True)

    if submitted and key_input.strip():
        ok, msg, hunts = activate_key(key_input.strip())
        st.session_state.activate_ok  = ok
        st.session_state.activate_msg = msg
        st.rerun()

    if st.session_state.activate_msg:
        if st.session_state.activate_ok:
            st.success(st.session_state.activate_msg)
        else:
            st.error(st.session_state.activate_msg)

# ===========================================================================
# PAGE: HUNT
# ===========================================================================
else:
    st.title("✨ Shiny Hunter — FRLG & BDSP")
    st.caption("Automated shiny hunting via capture card + Nintendo Switch controller emulation")

    unlocked_hunts = get_unlocked_hunts()

    # -----------------------------------------------------------------------
    # Sidebar — hunt configuration
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.header("⚙️ Configuration")
        settings = load_settings()

        capture_idx = st.number_input(
            "📺 Capture Card Device Index",
            min_value=0, max_value=10,
            value=int(settings.get("capture", {}).get("device_index", 0)),
            key="capture_idx_input",
            help="0 = first camera. Increase if you have a webcam already connected.",
        )

        if unlocked_hunts:
            target_options = [HUNT_CATALOGUE[h]["display"]
                              for h in unlocked_hunts if h in HUNT_CATALOGUE]
            target_display = st.selectbox(
                "🎯 Target Pokémon",
                options=target_options,
                key="target_select",
            )
            # Resolve display name → catalogue hunt_id (e.g. "Arceus (BDSP)" → "arceus")
            hunt_id = _DISPLAY_TO_ID.get(target_display, target_display.lower())
        else:
            st.warning("🔒 No hunts unlocked. Visit the **Store** tab to activate a key.")
            target_display = None
            hunt_id = None

        ctrl_mode = st.radio(
            "🎮 Controller Mode",
            options=["Keyboard (Test Mode)", "Serial (Arduino — Recommended)"],
            key="ctrl_mode_radio",
            help=(
                "**Keyboard**: simulates keypresses — only works with a PC emulator, "
                "NOT a real Switch.\n\n"
                "**Serial**: sends commands to an Arduino/Pro Micro plugged into the Switch."
            ),
        )

        serial_port = settings.get("controller", {}).get("serial_port", "COM3")
        if "Serial" in ctrl_mode:
            serial_port = st.text_input(
                "🔌 Arduino Serial Port",
                value=serial_port,
                key="serial_port_input",
                help="Windows: COM3, COM7 … | Linux/Mac: /dev/ttyUSB0",
            )

        st.divider()
        if target_display:
            st.markdown("**📋 Before you start:**")
            if hunt_id in BDSP_TARGETS:
                st.info(
                    f"Save at the top of Spear Pillar stairs, facing Arceus. "
                    f"Leave the game **running** (don't close it). The bot will close and reopen it each reset."
                )
            else:
                st.info(
                    f"Save immediately before encountering **{target_display}**. "
                    f"The bot will soft-reset and repeat until a shiny appears."
                )
        st.divider()
        if st.button("🛒 Unlock more hunts", use_container_width=True, key="goto_store_btn"):
            st.session_state.page = "Store"
            st.rerun()

    # -----------------------------------------------------------------------
    # Main content — Preview + Stats
    # -----------------------------------------------------------------------
    col_preview, col_stats = st.columns([2, 1])

    with col_preview:
        st.subheader("📺 Capture Preview")
        frame_display = st.empty()

        if not st.session_state.running:
            if st.button("🔍 Grab Preview Frame", use_container_width=True, key="preview_btn"):
                try:
                    with CaptureHandler(device_index=int(capture_idx)) as h:
                        frame = h.grab_frame()
                    if frame is not None:
                        frame_display.image(
                            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                            caption="Live capture preview",
                            use_container_width=True,
                        )
                    else:
                        st.error("No frame received. Check the device index.")
                except Exception as e:
                    st.error(f"Could not open device {capture_idx}: {e}")

        if st.session_state.shiny_found and st.session_state.last_frame is not None:
            frame_display.image(
                cv2.cvtColor(st.session_state.last_frame, cv2.COLOR_BGR2RGB),
                caption="🌟 Shiny detected!",
                use_container_width=True,
            )

    with col_stats:
        st.subheader("📊 Stats")

        if st.session_state.shiny_found:
            st.success(f"🌟 SHINY {(target_display or '').upper()} FOUND!")
        elif st.session_state.running:
            st.info("🔄 Hunt in progress…")
        else:
            st.warning("⏸️ Idle — press Start to begin")

        st.metric("Total Encounters", st.session_state.encounters)

        if st.session_state.start_time:
            elapsed = datetime.now() - st.session_state.start_time
            st.metric("Elapsed Time", str(timedelta(seconds=int(elapsed.total_seconds()))))
            if st.session_state.encounters > 0:
                rate = st.session_state.encounters / max(elapsed.total_seconds() / 60, 0.001)
                st.metric("Resets / min", f"{rate:.1f}")

        st.caption("Base shiny odds: **1 / 8192** (Gen 3)")

    # -----------------------------------------------------------------------
    # Controls — Start / Stop / Reset
    # -----------------------------------------------------------------------
    st.divider()
    col_start, col_stop, col_reset = st.columns(3)

    with col_start:
        if st.button(
            "▶ Start Hunting",
            type="primary",
            disabled=(st.session_state.running or st.session_state.shiny_found or hunt_id is None),
            use_container_width=True,
            key="start_btn",
        ):
            # Reset shared state
            _shared_state["running"]     = True
            _shared_state["shiny_found"] = False
            _shared_state["encounters"]  = 0
            _shared_state["last_frame"]  = None
            _current_sequence[0]         = None

            st.session_state.running      = True
            st.session_state.shiny_found  = False
            st.session_state.encounters   = 0
            st.session_state.log_messages = []
            st.session_state.start_time   = datetime.now()
            st.session_state.last_frame   = None

            thread = threading.Thread(
                target=run_hunt_thread,
                args=(int(capture_idx), hunt_id, ctrl_mode, serial_port),
                daemon=True,
            )
            st.session_state.hunt_thread = thread
            thread.start()
            st.rerun()

    with col_stop:
        if st.button(
            "⏹ Stop",
            type="secondary",
            disabled=not st.session_state.running,
            use_container_width=True,
            key="stop_btn",
        ):
            seq = _current_sequence[0]
            if seq:
                seq.stop()
            _shared_state["running"]    = False
            st.session_state.running    = False
            add_log("Hunt stopped by user.")
            st.rerun()

    with col_reset:
        if st.button("🔄 Reset Stats", use_container_width=True, key="reset_btn"):
            st.session_state.encounters   = 0
            st.session_state.shiny_found  = False
            st.session_state.log_messages = []
            st.session_state.start_time   = None
            st.session_state.last_frame   = None
            _shared_state["encounters"]   = 0
            _shared_state["shiny_found"]  = False
            _shared_state["last_frame"]   = None
            st.rerun()

    # -----------------------------------------------------------------------
    # Activity log
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("📝 Activity Log")
    flush_log_queue()
    if st.session_state.log_messages:
        log_text = "\n".join(reversed(st.session_state.log_messages[-40:]))
        st.text_area(
            "log",
            value=log_text,
            height=200,
            disabled=True,
            label_visibility="collapsed",
            key="log_area",
        )
    else:
        st.caption("Log will appear here once the hunt starts.")

    # -----------------------------------------------------------------------
    # Auto-refresh while running
    # -----------------------------------------------------------------------
    if st.session_state.running:
        time.sleep(2)
        st.rerun()
