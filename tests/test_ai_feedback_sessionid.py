from argparse import Namespace

from ai_feedback import make_record


def test_make_record_contains_sessionid():
    args = Namespace(task_id="11", source_ai="codex", sessionid="sid-11")
    row = make_record(args, "db", "done")
    assert '"sessionid": "sid-11"' in row

