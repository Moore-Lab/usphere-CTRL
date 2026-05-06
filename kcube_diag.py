"""
kcube_diag.py - KCube / KDC101 connection diagnostic

Attempts every step of the connection sequence separately and prints the
full exception at the first failure, so you can see the real error instead
of a bare "connection failed" from the GUI.

Usage
-----
    python kcube_diag.py                    # serial from session_state.json
    python kcube_diag.py --serial 27006288  # explicit override
    python kcube_diag.py --list             # list all detected Kinesis USB devices
    python kcube_diag.py --home             # connect + home (if connection succeeds)
    python kcube_diag.py --move 6.5         # connect + move to 6.5 mm

Exit codes
----------
0  all requested steps succeeded
1  a step failed (error printed to stdout)
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE          = Path(__file__).parent
_SESSION_STATE = _HERE / "session_state.json"
_STAGE_STATE   = _HERE / "modules" / "dropper_stage_state.json"
_SUBMODULE_DIR = _HERE / "resources" / "kcube-motor-controller"

if _SUBMODULE_DIR.exists() and str(_SUBMODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_SUBMODULE_DIR))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(title: str) -> None:
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL]  {msg}")


def _info(msg: str) -> None:
    print(f"  {msg}")


def _read_serial_from_state() -> str | None:
    """Return the serial number saved in session_state.json, or None."""
    try:
        state = json.loads(_SESSION_STATE.read_text(encoding="utf-8"))
        sn = state.get("dropper", {}).get("serial_number")
        return str(sn).strip() if sn else None
    except Exception:
        return None


def _read_last_position() -> float | None:
    """Return the last saved stage position from dropper_stage_state.json."""
    for candidate in [_STAGE_STATE, _HERE / "ipc" / "dropper_stage_state.json"]:
        try:
            d = json.loads(candidate.read_text(encoding="utf-8"))
            pos = d.get("last_position_mm")
            if pos is not None:
                return float(pos)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Diagnostic steps
# ---------------------------------------------------------------------------

def check_pylablib() -> bool:
    _banner("Step 1 -pylablib import")
    try:
        from pylablib.devices import Thorlabs   # noqa: F401
        _ok("pylablib imported successfully")
        return True
    except ImportError as exc:
        _fail(f"pylablib not importable: {exc}")
        print()
        print("  Fix: pip install pylablib")
        print("  Also ensure Thorlabs Kinesis is installed:")
        print("    https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control")
        return False


def check_kinesis_dll() -> bool:
    _banner("Step 2 -Kinesis DLL discovery")
    try:
        from pylablib.devices import Thorlabs
        devs = Thorlabs.list_kinesis_devices()
        _ok(f"Kinesis SDK accessible -{len(devs)} device(s) detected")
        if devs:
            for sn, desc in devs:
                _info(f"  S/N {sn}  - {desc}")
        else:
            _info("No devices found via USB (check cable and power)")
        return True
    except Exception as exc:
        _fail(f"Kinesis DLL error: {exc}")
        traceback.print_exc()
        return False


def list_devices() -> list[str]:
    """Return serial numbers as strings; print them too."""
    _banner("Kinesis USB device list")
    try:
        from pylablib.devices import Thorlabs
        devs = Thorlabs.list_kinesis_devices()
        if not devs:
            _info("No devices detected")
            return []
        for sn, desc in devs:
            _info(f"  S/N {sn}  - {desc}")
        return [str(sn) for sn, _ in devs]
    except Exception as exc:
        _fail(f"Could not list devices: {exc}")
        traceback.print_exc()
        return []


def check_connection(serial: str) -> "KCubeConnection | None":
    """Try every substep of KCubeConnection.connect() and report the failure point."""
    _banner(f"Step 3 -Connection to S/N {serial}")

    # --- import
    try:
        from kcube_connection import KCubeConnection, PYLABLIB_AVAILABLE
    except ImportError as exc:
        _fail(f"Cannot import KCubeConnection: {exc}")
        return None

    if not PYLABLIB_AVAILABLE:
        _fail("PYLABLIB_AVAILABLE is False inside kcube_connection -import failed silently")
        return None
    _ok("KCubeConnection importable")

    # --- instantiate KinesisMotor (does not open USB yet)
    try:
        from pylablib.devices import Thorlabs
        _info(f"Instantiating KinesisMotor('{serial}', scale=34304) ...")
        motor = Thorlabs.KinesisMotor(serial, scale=34304)
        _ok("KinesisMotor instantiated (device not opened yet)")
    except Exception as exc:
        _fail(f"KinesisMotor() constructor raised: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None

    # --- open USB connection
    import time
    try:
        _info("Calling motor.open() ...")
        motor.open()
        _ok("motor.open() succeeded")
    except Exception as exc:
        _fail(f"motor.open() raised: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None

    # --- settle
    _info("Sleeping 0.5 s for USB-serial settle ...")
    time.sleep(0.5)

    # --- build and return a live KCubeConnection wrapping this motor
    conn = KCubeConnection(serial, scale=34304)
    conn._motor     = motor
    conn._connected = True
    _ok(f"Connected to S/N {serial}")
    return conn


def check_status(conn: "KCubeConnection") -> bool:
    _banner("Step 4 -Status readback")
    try:
        pos_set = float(conn.motor.get_position())
        _ok(f"get_position() (commanded):  {pos_set:.6f} mm")
    except Exception as exc:
        _fail(f"get_position() raised: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False
    try:
        pos_enc = float(conn.motor.get_encoder(scale=True))
        _ok(f"get_encoder()  (actual enc): {pos_enc:.6f} mm")
    except AttributeError:
        _info("get_encoder() not available on this pylablib version")

    try:
        status = conn.motor.get_status()
        _ok(f"Status flags: {status}")
    except Exception as exc:
        _info(f"get_status() raised (non-fatal): {type(exc).__name__}: {exc}")

    last = _read_last_position()
    if last is not None:
        _info(f"Last saved position (dropper_stage_state.json): {last:.6f} mm")

    return True


def do_home(conn: "KCubeConnection") -> None:
    _banner("Homing")
    try:
        _info("Sending home command (this may take up to 60 s) ...")
        conn.motor.home(sync=True, timeout=60.0)
        pos = float(conn.motor.get_position())
        _ok(f"Homed -position: {pos:.6f} mm")
    except Exception as exc:
        _fail(f"home() raised: {type(exc).__name__}: {exc}")
        traceback.print_exc()


def do_move(conn: "KCubeConnection", target_mm: float) -> None:
    _banner(f"Move to {target_mm} mm")
    try:
        conn.motor.move_to(target_mm)
        conn.motor.wait_move(timeout=60.0)
        pos = float(conn.motor.get_position())
        _ok(f"Moved -position: {pos:.6f} mm")
    except Exception as exc:
        _fail(f"move raised: {type(exc).__name__}: {exc}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="KCube / KDC101 connection diagnostic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--serial", metavar="SN",
                   help="Serial number to connect to (default: read from session_state.json)")
    p.add_argument("--list", action="store_true",
                   help="List all detected Kinesis USB devices and exit")
    p.add_argument("--home", action="store_true",
                   help="Home the stage after connecting")
    p.add_argument("--move", metavar="MM", type=float,
                   help="Move to this absolute position (mm) after connecting")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    print("=" * 60)
    print("  usphere  KCube / KDC101 diagnostic")
    print("=" * 60)

    # --list short-circuits everything
    if args.list:
        if not check_pylablib():
            return 1
        list_devices()
        return 0

    # Resolve serial number
    if args.serial:
        serial = args.serial.strip()
        _info(f"Serial: {serial}  (from --serial argument)")
    else:
        serial = _read_serial_from_state()
        if serial:
            _info(f"Serial: {serial}  (from session_state.json)")
        else:
            from modules.mod_dropper_stage import CONFIG_FIELDS
            serial = str(CONFIG_FIELDS[0]["default"])
            _info(f"Serial: {serial}  (module default -session_state.json not found)")

    # Run diagnostic steps
    if not check_pylablib():
        return 1

    if not check_kinesis_dll():
        return 1

    conn = check_connection(serial)
    if conn is None:
        return 1

    ok = check_status(conn)

    if args.home:
        do_home(conn)

    if args.move is not None:
        do_move(conn, args.move)

    # Cleanup
    _banner("Disconnect")
    try:
        conn.motor.close()
        _ok("Disconnected cleanly")
    except Exception as exc:
        _info(f"Close raised (non-fatal): {exc}")

    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
