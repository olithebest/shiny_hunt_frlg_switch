"""
Shiny Hunter FRLG Switch — Streamlit GUI
Run with: streamlit run src/gui/app.py
"""

import sys
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

# Make the project root importable regardless of where streamlit is launched from
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.capture.capture_handler import CaptureHandler
from src.detection.shiny_detector import ShinyDetector
from src.controller.switch_controller import SwitchController, ControllerMode
from src.automation.sequences import HuntSequence
from src.licensing.license_manager import HUNT_CATALOGUE, get_unlocked_hunts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="✨ Shiny Hunter FRLG",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state
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


def add_log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.log_messages.append(f"[{ts}] {msg}")
    if len(st.session_state.log_messages) > 200:
        st.session_state.log_messages = st.session_state.log_messages[-200:]


def run_hunt_thread(capture_idx: int, target: str, ctrl_mode: str, serial_port: str):
    """Runs in a background daemon thread — owns the capture/controller lifecycle."""
    try:
        mode = (ControllerMode.SERIAL
                if "Serial" in ctrl_mode
                else ControllerMode.KEYBOARD)

        capture    = CaptureHandler(device_index=capture_idx)
        detector   = ShinyDetector()
        controller = SwitchController(mode=mode, port=serial_port)

        sequence = HuntSequence(
            target=target,
            controller=controller,
            detector=detector,
            capture=capture,
            on_status=add_log,
            on_encounter=lambda count, shiny: _on_encounter(count, shiny),
        )
        st.session_state.sequence = sequence

        capture.open()
        controller.connect()
        try:
            result = sequence.run()
            if result.is_shiny:
                add_log(f"🌟 SHINY {target.upper()} found after {result.encounters} encounters!")
                st.session_state.shiny_found = True
                st.session_state.last_frame  = result.frame
        finally:
            capture.close()
            controller.disconnect()

    except Exception as exc:
        add_log(f"ERROR: {exc}")
        logging.exception("Hunt thread crashed")
    finally:
        st.session_state.running = False


def _on_encounter(count: int, is_shiny: bool):
    st.session_state.encounters = count
    if is_shiny:
        st.session_state.shiny_found = True


# ---------------------------------------------------------------------------
# UI — Header
# ---------------------------------------------------------------------------
st.title("✨ Shiny Hunter — Pokémon Fire Red / Leaf Green")
st.caption("Automated shiny hunting via capture card + Nintendo Switch controller emulation")

unlocked_hunts = get_unlocked_hunts()

# ---------------------------------------------------------------------------
# UI — Sidebar (configuration)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuration")
    settings = load_settings()

    capture_idx = st.number_input(
        "📺 Capture Card Device Index",
        min_value=0, max_value=10,
        value=int(settings.get("capture", {}).get("device_index", 0)),
        help="0 = first camera. Increase by 1 if you have a webcam already connected.",
    )

    if unlocked_hunts:
        target_options = [HUNT_CATALOGUE[h]["display"]
                          for h in unlocked_hunts if h in HUNT_CATALOGUE]
        target = st.selectbox("🎯 Target Pokémon", options=target_options)
    else:
        st.warning("🔒 No hunts unlocked. Run **store_server.py** to activate a license key.")
        target = None

    ctrl_mode = st.radio(
        "🎮 Controller Mode",
        options=["Keyboard (Test Mode)", "Serial (Arduino — Recommended)"],
        help=(
            "**Keyboard**: simulates keypresses — only works with a PC emulator, "
            "NOT a real Switch.\n\n"
            "**Serial**: sends commands to an Arduino Leonardo/Pro Micro that is "
            "plugged into the Switch via USB and acts as a Pro Controller."
        ),
    )

    serial_port = settings.get("controller", {}).get("serial_port", "COM3")
    if "Serial" in ctrl_mode:
        serial_port = st.text_input(
            "🔌 Arduino Serial Port",
            value=serial_port,
            help="Windows: COM3, COM4 … | Linux/Mac: /dev/ttyUSB0",
        )

    st.divider()
    if target:
        st.markdown("**📋 Before you start:**")
        st.info(
            f"Save your game immediately before encountering **{target}**. "
            f"The bot will load that save and repeat until a shiny appears."
        )

    st.divider()
    st.caption("To unlock more hunts, run:  \n`python store_server.py`")

# ---------------------------------------------------------------------------
# UI — Main content
# ---------------------------------------------------------------------------
col_preview, col_stats = st.columns([2, 1])

with col_preview:
    st.subheader("📺 Capture Preview")
    frame_display = st.empty()

    if not st.session_state.running:
        if st.button("🔍 Grab Preview Frame", use_container_width=True):
            try:
                with CaptureHandler(device_index=int(capture_idx)) as h:
                    frame = h.grab_frame()
                if frame is not None:
                    frame_display.image(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                        caption="Live capture preview",
                        use_column_width=True,
                    )
                else:
                    st.error("No frame received. Check the device index.")
            except Exception as e:
                st.error(f"Could not open device {capture_idx}: {e}")

    if st.session_state.shiny_found and st.session_state.last_frame is not None:
        frame_display.image(
            cv2.cvtColor(st.session_state.last_frame, cv2.COLOR_BGR2RGB),
            caption="🌟 Shiny detected!",
            use_column_width=True,
        )

with col_stats:
    st.subheader("📊 Stats")

    if st.session_state.shiny_found:
        st.success(f"🌟 SHINY {(target or '').upper()} FOUND!")
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

    st.caption("Base shiny odds in Gen 3: **1 / 8192**")

# ---------------------------------------------------------------------------
# UI — Controls
# ---------------------------------------------------------------------------
st.divider()
col_start, col_stop, col_reset = st.columns(3)

with col_start:
    if st.button(
        "▶ Start Hunting",
        type="primary",
        disabled=(
            st.session_state.running
            or st.session_state.shiny_found
            or target is None
        ),
        use_container_width=True,
    ):
        st.session_state.running     = True
        st.session_state.shiny_found  = False
        st.session_state.encounters   = 0
        st.session_state.log_messages = []
        st.session_state.start_time   = datetime.now()
        st.session_state.last_frame   = None

        thread = threading.Thread(
            target=run_hunt_thread,
            args=(int(capture_idx), target.lower(), ctrl_mode, serial_port),
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
    ):
        seq: Optional[HuntSequence] = st.session_state.sequence
        if seq:
            seq.stop()
        st.session_state.running = False
        add_log("Hunt stopped by user.")
        st.rerun()

with col_reset:
    if st.button("🔄 Reset Stats", use_container_width=True):
        st.session_state.encounters   = 0
        st.session_state.shiny_found  = False
        st.session_state.log_messages = []
        st.session_state.start_time   = None
        st.session_state.last_frame   = None
        st.rerun()

# ---------------------------------------------------------------------------
# UI — Activity log
# ---------------------------------------------------------------------------
st.divider()
st.subheader("📝 Activity Log")
if st.session_state.log_messages:
    log_text = "\n".join(reversed(st.session_state.log_messages[-40:]))
    st.text_area(
        "log",
        value=log_text,
        height=200,
        disabled=True,
        label_visibility="collapsed",
    )
else:
    st.caption("Log will appear here once the hunt starts.")

# ---------------------------------------------------------------------------
# Auto-refresh while hunt is running (polls every 2 seconds)
# ---------------------------------------------------------------------------
if st.session_state.running:
    time.sleep(2)
    st.rerun()


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="✨ Shiny Hunter FRLG",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "running":        False,
    "encounters":     0,
    "shiny_found":    False,
    "log_messages":   [],
    "start_time":     None,
    "hunt_thread":    None,
    "sequence":       None,
    "last_frame":     None,
    "activate_msg":   None,
    "activate_ok":    None,
    "page":           "Hunt",
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


def add_log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.log_messages.append(f"[{ts}] {msg}")
    if len(st.session_state.log_messages) > 200:
        st.session_state.log_messages = st.session_state.log_messages[-200:]


def run_hunt_thread(capture_idx: int, target: str, ctrl_mode: str, serial_port: str):
    """Runs in a background daemon thread — owns the capture/controller lifecycle."""
    try:
        mode = (ControllerMode.SERIAL
                if "Serial" in ctrl_mode
                else ControllerMode.KEYBOARD)

        capture    = CaptureHandler(device_index=capture_idx)
        detector   = ShinyDetector()
        controller = SwitchController(mode=mode, port=serial_port)

        sequence = HuntSequence(
            target=target,
            controller=controller,
            detector=detector,
            capture=capture,
            on_status=add_log,
            on_encounter=lambda count, shiny: _on_encounter(count, shiny),
        )
        st.session_state.sequence = sequence

        capture.open()
        controller.connect()
        try:
            result = sequence.run()
            if result.is_shiny:
                add_log(f"🌟 SHINY {target.upper()} found after {result.encounters} encounters!")
                st.session_state.shiny_found = True
                st.session_state.last_frame  = result.frame
        finally:
            capture.close()
            controller.disconnect()

    except Exception as exc:
        add_log(f"ERROR: {exc}")
        logging.exception("Hunt thread crashed")
    finally:
        st.session_state.running = False


def _on_encounter(count: int, is_shiny: bool):
    st.session_state.encounters = count
    if is_shiny:
        st.session_state.shiny_found = True


# ---------------------------------------------------------------------------
# Sidebar — navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ✨ Shiny Hunter FRLG")
    page = st.radio(
        "Navigate",
        options=["Hunt", "Store"],
        index=["Hunt", "Store"].index(st.session_state.page),
        label_visibility="collapsed",
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
        "Purchase a hunt on **itch.io**, receive your license key by email, "
        "and paste it below to activate."
    )

    # --- Catalogue grid ---
    unlocked = get_unlocked_hunts()
    cols = st.columns(min(len(HUNT_CATALOGUE), 4))
    for i, (hunt_id, info) in enumerate(HUNT_CATALOGUE.items()):
        col = cols[i % len(cols)]
        with col:
            locked = hunt_id not in unlocked
            badge  = "🔒 Locked" if locked else "✅ Unlocked"
            color  = info["color"]
            label  = info["display"]
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
                        {label}
                    </div>
                    <div style="color: #aaa; font-size: 0.9rem;">{badge}</div>
                    <div style="font-weight: bold; margin-top: 8px; color: white;">{price}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    # --- Activate key form ---
    st.subheader("🔑 Activate a License Key")
    st.markdown("Paste the key exactly as you received it:")

    with st.form("activate_form"):
        key_input = st.text_input(
            "License Key",
            placeholder="MEWTWO-XXXXXXXXXXXXXX-XXXXXXXX",
            label_visibility="collapsed",
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

    st.divider()
    st.markdown(
        "**Buy hunts on itch.io →** *(link coming soon)*  \n"
        "After purchase you will receive a license key by email within minutes."
    )

# ===========================================================================
# PAGE: HUNT
# ===========================================================================
else:
    # -----------------------------------------------------------------------
    # UI — Header
    # -----------------------------------------------------------------------
    st.title("✨ Shiny Hunter — Pokémon Fire Red / Leaf Green")
    st.caption("Automated shiny hunting via capture card + Nintendo Switch controller emulation")

    unlocked_hunts = get_unlocked_hunts()

    # -----------------------------------------------------------------------
    # UI — Sidebar (configuration)
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.header("⚙️ Configuration")
        settings = load_settings()

        capture_idx = st.number_input(
            "📺 Capture Card Device Index",
            min_value=0, max_value=10,
            value=int(settings.get("capture", {}).get("device_index", 0)),
            help="0 = first camera. Increase by 1 if you have a webcam already connected.",
        )

        # Only show hunts the user has unlocked
        if unlocked_hunts:
            target_options = [HUNT_CATALOGUE[h]["display"]
                              for h in unlocked_hunts if h in HUNT_CATALOGUE]
            target = st.selectbox(
                "🎯 Target Pokémon",
                options=target_options,
            )
        else:
            st.warning("🔒 No hunts unlocked yet. Visit the **Store** tab to activate a key.")
            target = None

        ctrl_mode = st.radio(
            "🎮 Controller Mode",
            options=["Keyboard (Test Mode)", "Serial (Arduino — Recommended)"],
            help=(
                "**Keyboard**: simulates keypresses — only works with a PC emulator, "
                "NOT a real Switch.\n\n"
                "**Serial**: sends commands to an Arduino Leonardo/Pro Micro that is "
                "plugged into the Switch via USB and acts as a Pro Controller."
            ),
        )

        serial_port = settings.get("controller", {}).get("serial_port", "COM3")
        if "Serial" in ctrl_mode:
            serial_port = st.text_input(
                "🔌 Arduino Serial Port",
                value=serial_port,
                help="Windows: COM3, COM4 … | Linux/Mac: /dev/ttyUSB0",
            )

        st.divider()
        if target:
            st.markdown("**📋 Before you start:**")
            st.info(
                f"Save your game immediately before encountering **{target}**. "
                f"The bot will load that save and repeat until a shiny appears."
            )

        st.divider()
        if st.button("🛒 Unlock more hunts", use_container_width=True):
            st.session_state.page = "Store"
            st.rerun()

    # -----------------------------------------------------------------------
    # UI — Main content
    # -----------------------------------------------------------------------
    col_preview, col_stats = st.columns([2, 1])

    with col_preview:
        st.subheader("📺 Capture Preview")
        frame_display = st.empty()

        if not st.session_state.running:
            if st.button("🔍 Grab Preview Frame", use_container_width=True):
                try:
                    with CaptureHandler(device_index=int(capture_idx)) as h:
                        frame = h.grab_frame()
                    if frame is not None:
                        frame_display.image(
                            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                            caption="Live capture preview",
                            use_column_width=True,
                        )
                    else:
                        st.error("No frame received. Check the device index.")
                except Exception as e:
                    st.error(f"Could not open device {capture_idx}: {e}")

        if st.session_state.shiny_found and st.session_state.last_frame is not None:
            frame_display.image(
                cv2.cvtColor(st.session_state.last_frame, cv2.COLOR_BGR2RGB),
                caption="🌟 Shiny detected!",
                use_column_width=True,
            )

    with col_stats:
        st.subheader("📊 Stats")

        if st.session_state.shiny_found:
            st.success(f"🌟 SHINY {(target or '').upper()} FOUND!")
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

        st.caption("Base shiny odds in Gen 3: **1 / 8192**")

    # -----------------------------------------------------------------------
    # UI — Controls
    # -----------------------------------------------------------------------
    st.divider()
    col_start, col_stop, col_reset = st.columns(3)

    with col_start:
        if st.button(
            "▶ Start Hunting",
            type="primary",
            disabled=(
                st.session_state.running
                or st.session_state.shiny_found
                or target is None
            ),
            use_container_width=True,
        ):
            st.session_state.running     = True
            st.session_state.shiny_found  = False
            st.session_state.encounters   = 0
            st.session_state.log_messages = []
            st.session_state.start_time   = datetime.now()
            st.session_state.last_frame   = None

            thread = threading.Thread(
                target=run_hunt_thread,
                args=(int(capture_idx), target.lower(), ctrl_mode, serial_port),
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
        ):
            seq: Optional[HuntSequence] = st.session_state.sequence
            if seq:
                seq.stop()
            st.session_state.running = False
            add_log("Hunt stopped by user.")
            st.rerun()

    with col_reset:
        if st.button("🔄 Reset Stats", use_container_width=True):
            st.session_state.encounters   = 0
            st.session_state.shiny_found  = False
            st.session_state.log_messages = []
            st.session_state.start_time   = None
            st.session_state.last_frame   = None
            st.rerun()

    # -----------------------------------------------------------------------
    # UI — Activity log
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("📝 Activity Log")
    if st.session_state.log_messages:
        log_text = "\n".join(reversed(st.session_state.log_messages[-40:]))
        st.text_area(
            "log",
            value=log_text,
            height=200,
            disabled=True,
            label_visibility="collapsed",
        )
    else:
        st.caption("Log will appear here once the hunt starts.")

    # -----------------------------------------------------------------------
    # Auto-refresh while hunt is running (polls every 2 seconds)
    # -----------------------------------------------------------------------
    if st.session_state.running:
        time.sleep(2)
        st.rerun()

