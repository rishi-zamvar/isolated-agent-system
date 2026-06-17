import json

from agentctl import cli, store


def test_send_validates_stores_and_wakes(store_path, wake_dir, capsys):
    rc = cli.main([
        "--store", str(store_path), "--wake-dir", str(wake_dir),
        "send", "--from", "pm", "--to", "tl", "--type", "Ticket",
        "--event", "TICKET_OPENED", "--payload", json.dumps({"n": 1}),
    ])
    assert rc == 0
    rows = store.inbox(store_path, "tl")
    assert len(rows) == 1
    assert list(wake_dir.glob("wake__tl__*.touch"))  # doorbell fired
    out = capsys.readouterr().out
    assert "sent" in out and rows[0]["id"] in out


def test_send_rejects_r2_violation_nonzero_exit(store_path, wake_dir):
    rc = cli.main([
        "--store", str(store_path), "--wake-dir", str(wake_dir),
        "send", "--from", "pm", "--to", "be", "--type", "FreeText",
        "--event", "X", "--payload", "{}",
    ])
    assert rc != 0
    assert store.inbox(store_path, "be") == []  # nothing stored


def test_inbox_lists_then_read_marks(store_path, wake_dir, capsys):
    cli.main(["--store", str(store_path), "--wake-dir", str(wake_dir),
              "send", "--from", "pm", "--to", "tl", "--type", "Ticket",
              "--event", "TICKET_OPENED", "--payload", json.dumps({"n": 1})])
    capsys.readouterr()  # clear

    rc = cli.main(["--store", str(store_path), "--wake-dir", str(wake_dir),
                   "inbox", "--role", "tl", "--unread"])
    assert rc == 0
    line = capsys.readouterr().out.strip()
    assert "tl" in line and "Ticket" in line
    env_id = store.inbox(store_path, "tl")[0]["id"]

    rc = cli.main(["--store", str(store_path), "--wake-dir", str(wake_dir),
                   "read", env_id])
    assert rc == 0
    assert store.inbox(store_path, "tl", unread_only=True) == []
