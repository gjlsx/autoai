from pty_worker import InputEnvelope, PtyWorker


def test_parse_plain_text():
    env = PtyWorker.parse_input("hello world")
    assert isinstance(env, InputEnvelope)
    assert env.message == "hello world"
    assert env.task_id is None


def test_parse_json_payload():
    env = PtyWorker.parse_input('{"task_id":"9","message":"run test","source":"dispatcher","x":1}')
    assert isinstance(env, InputEnvelope)
    assert env.message == "run test"
    assert env.task_id == "9"
    assert env.source == "dispatcher"
    assert env.meta["x"] == "1"
