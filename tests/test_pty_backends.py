from pty_backends import ProbeResult, recommend_backend


def test_recommend_backend_prefers_pywinpty():
    results = [
        ProbeResult("pywinpty", True, 100, "ok"),
        ProbeResult("node-pty", True, 80, "ok"),
        ProbeResult("native-conpty", True, 10, "ok"),
    ]
    assert recommend_backend(results) == "pywinpty"


def test_recommend_backend_fallback_order():
    results = [
        ProbeResult("pywinpty", False, 100, "fail"),
        ProbeResult("node-pty", True, 80, "ok"),
        ProbeResult("native-conpty", True, 10, "ok"),
    ]
    assert recommend_backend(results) == "node-pty"

    results = [
        ProbeResult("pywinpty", False, 100, "fail"),
        ProbeResult("node-pty", False, 80, "fail"),
        ProbeResult("native-conpty", True, 10, "ok"),
    ]
    assert recommend_backend(results) == "native-conpty"
