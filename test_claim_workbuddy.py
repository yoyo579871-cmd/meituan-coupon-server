import contextlib
import io
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import claim_workbuddy as claim


class Response:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.body


class ClaimTests(unittest.TestCase):
    def run_case(self, body=None, args=None, error=None, token="fake-test-token"):
        output = io.StringIO()
        calls = []

        def opener(request, timeout):
            calls.append(request)
            if error:
                raise error
            return Response(body)

        with tempfile.TemporaryDirectory() as directory:
            summary = os.path.join(directory, "summary.md")
            with patch.dict(os.environ, {"MEITUAN_PT_TOKEN": token,
                                        "MEITUAN_AI_SCENE": claim.DEFAULT_SCENE,
                                        "GITHUB_STEP_SUMMARY": summary}, clear=True):
                with contextlib.redirect_stdout(output):
                    result = claim.main(args or [], opener)
            with open(summary, encoding="utf-8") as stream:
                summary_text = stream.read()
        return result, output.getvalue(), calls, summary_text

    def test_1014_is_failure_not_already_received(self):
        rc, log, calls, summary = self.run_case(b'{"code":1014,"msg":"rejected"}')
        self.assertEqual(rc, 1)
        self.assertIn("claim_rejected_reason_unknown", summary)
        self.assertNotIn("[SUCCESS]", log)
        self.assertEqual(len(calls), 1)

    def test_only_nonempty_coupon_list_is_confirmed(self):
        for body, expected in [(b'{"code":200,"data":{"couponList":[{}]}}', 0),
                               (b'{"code":200,"data":{"couponList":[]}}', 1),
                               (b'{"code":200,"data":{}}', 1),
                               (b'{"code":200,"data":{"couponList":[null]}}', 1),
                               (b'[]', 1), (b'{"code":401}', 1),
                               (b'{"code":509}', 1), (b'{"code":9999}', 1)]:
            with self.subTest(body=body):
                self.assertEqual(self.run_case(body)[0], expected)

    def test_config_check_never_sends_request(self):
        rc, log, calls, summary = self.run_case(args=["--check-config"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertIn("token_sha256_16=", log)
        self.assertNotIn("fake-test-token", log + summary)

    def test_missing_token_never_sends_request(self):
        rc, _, calls, _ = self.run_case(token="")
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])

    def test_bad_json_does_not_echo_body(self):
        rc, log, _, _ = self.run_case(b'<html>fake-test-token</html>')
        self.assertEqual(rc, 1)
        self.assertNotIn("fake-test-token", log)

    def test_response_message_redacts_token_and_newlines(self):
        _, log, _, summary = self.run_case(b'{"code":1014,"msg":"fake-test-token\\n::warning::x"}')
        self.assertNotIn("fake-test-token", log + summary)
        self.assertNotIn("\n::warning::", log)

    def test_http_error_cannot_become_success(self):
        error = urllib.error.HTTPError(claim.ENDPOINT, 403, "Forbidden", {},
                                      io.BytesIO(b'{"code":200,"data":{"couponList":[{}]}}'))
        self.assertEqual(self.run_case(error=error)[0], 1)

    def test_network_error_is_not_retried(self):
        rc, log, calls, _ = self.run_case(error=urllib.error.URLError("fake-test-token"))
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("fake-test-token", log)


if __name__ == "__main__":
    unittest.main()
