"""El servicio late el heartbeat en un spool de prueba y se frena limpio."""

import time

from universal_bot.labcode_service import main


def test_start_beats_and_stop_is_clean(tmp_path):
    spool = tmp_path / "spool"
    db = tmp_path / "state" / "labcode.sqlite"
    log = tmp_path / "runtime.log"
    pidfile = tmp_path / "runtime.pid"
    args = [
        "--spool",
        str(spool),
        "--db",
        str(db),
        "--log",
        str(log),
        "--pidfile",
        str(pidfile),
        "--interval",
        "1",
    ]
    try:
        assert main(["start", *args]) == 0
        heart = spool / "runtime.heartbeat"
        deadline = time.time() + 20
        while time.time() < deadline and not heart.is_file():
            time.sleep(0.1)
        assert heart.is_file()
        report = main(["status", *args])
        assert isinstance(report, str)
        assert report.startswith("activo ")
        age = float(report.removeprefix("activo edad=").rstrip("s"))
        assert age < 20
    finally:
        main(["stop", *args])
    assert pidfile.exists() is False
