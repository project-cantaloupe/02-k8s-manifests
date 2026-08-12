import base64
import hashlib
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


class RunnerLimitTest(unittest.TestCase):
    def test_load_count_allows_reactive_run_below_safety_cap(self):
        with mock.patch.dict("os.environ", {"LOAD_COUNT": "150"}):
            runner = load_runner()

        self.assertEqual(runner["MAX_COUNT"], 200)
        self.assertEqual(runner["COUNT"], 150)

    def test_load_count_is_capped_at_two_hundred(self):
        with mock.patch.dict("os.environ", {"LOAD_COUNT": "250"}):
            runner = load_runner()

        self.assertEqual(runner["COUNT"], 200)


class RunnerPresentationTest(unittest.TestCase):
    def test_visibility_defaults_to_public(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            runner = load_runner()

        self.assertEqual(runner["VISIBILITY"], "public")

    def test_title_explains_phase_profile_time_sequence_and_fixture(self):
        env = {
            "RUN_ID": "audio-finops-reactive-150-20260812-124826",
            "LOAD_PROFILE": "unexpected-burst",
            "EXPERIMENT_PHASE": "baseline",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            runner = load_runner()

        title = runner["track_title"](0, 0, 15)

        self.assertEqual(
            title,
            "FinOps Baseline · Reactive Burst · 08/12 21:48 KST · #001 · 15초 · 패턴 1",
        )
        self.assertLessEqual(len(title), 200)


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


class RunnerFixtureTest(unittest.TestCase):
    def setUp(self):
        self.runner = load_runner()

    def test_prepare_fixtures_generates_each_fixture_once(self):
        generated = []

        def make_wav(index):
            generated.append(index)
            return f"wav-{index}".encode(), index + 1

        self.runner["make_wav"] = make_wav
        with mock.patch("builtins.print"):
            cache = self.runner["prepare_fixtures"]()

        self.assertEqual(generated, list(range(len(self.runner["FIXTURES"]))))
        self.assertEqual(len(cache), len(self.runner["FIXTURES"]))
        for index, (wav_bytes, seconds, checksum) in enumerate(cache):
            expected = f"wav-{index}".encode()
            self.assertEqual(wav_bytes, expected)
            self.assertEqual(seconds, index + 1)
            self.assertEqual(
                checksum,
                base64.b64encode(hashlib.sha256(expected).digest()).decode(),
            )

    def test_upload_one_reuses_cached_fixture(self):
        fixture_cache = ((b"cached-wav", 15, "cached-checksum"),)
        requests = []

        def api_request_json(method, path, body=None, timeout=60):
            requests.append((method, path, body, timeout))
            if path == "/v1/audios/uploads":
                return {
                    "audio_id": "audio-1",
                    "upload_url": "https://upload.example.test/audio-1",
                    "upload_headers": {},
                }
            return {"status": "SCAN_PENDING"}

        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__exit__.return_value = False
        self.runner["api_request_json"] = api_request_json
        self.runner["make_wav"] = mock.Mock(
            side_effect=AssertionError("unexpected WAV generation")
        )

        with mock.patch("urllib.request.urlopen", return_value=response):
            item = self.runner["upload_one"](0, fixture_cache)

        self.assertEqual(item["audio_id"], "audio-1")
        self.assertEqual(item["source_seconds"], 15)
        self.assertEqual(requests[0][2]["checksum_sha256"], "cached-checksum")
        self.assertEqual(requests[0][2]["visibility"], "public")
        self.assertEqual(
            requests[0][2]["title"], self.runner["track_title"](0, 0, 15)
        )
        self.runner["make_wav"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
