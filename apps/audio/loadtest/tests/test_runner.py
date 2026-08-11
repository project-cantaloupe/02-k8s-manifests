import io
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[4]


def load_runner():
    lines = (ROOT / "apps/audio/loadtest/runner-configmap.yaml").read_text(
        encoding="utf-8"
    ).splitlines()
    start = lines.index("  runner.py: |") + 1
    source = []
    for line in lines[start:]:
        if line.startswith("    "):
            source.append(line[4:])
        elif not line:
            source.append("")
        else:
            break
    namespace = {"__name__": "runner_test"}
    exec(compile("\n".join(source), "runner.py", "exec"), namespace)
    return namespace


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class RunnerAuthTest(unittest.TestCase):
    def setUp(self):
        self.runner = load_runner()
        self.runner["OIDC_CLIENT_ID"] = "audio-finops"
        self.runner["OIDC_CLIENT_SECRET"] = "test-only-secret"

    def test_client_credentials_token_is_cached(self):
        response = FakeResponse(b'{"access_token":"token-1","expires_in":300}')
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(self.runner["access_token"](), "token-1")
            self.assertEqual(self.runner["access_token"](), "token-1")
        self.assertEqual(urlopen.call_count, 1)

    def test_api_request_uses_bearer_token_on_internal_api(self):
        calls = []

        def request_json(method, url, body=None, headers=None, timeout=60):
            calls.append((method, url, body, headers, timeout))
            return {"status": "ok"}

        self.runner["request_json"] = request_json
        self.runner["access_token"] = lambda: "token-2"
        result = self.runner["api_request_json"]("GET", "/v1/audios?scope=public")

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(calls[0][1], self.runner["API"] + "/v1/audios?scope=public")
        self.assertEqual(calls[0][3], {"Authorization": "Bearer token-2"})


if __name__ == "__main__":
    unittest.main()
