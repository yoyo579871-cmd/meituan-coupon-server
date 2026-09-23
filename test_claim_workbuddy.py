import contextlib
import io
import json
import os
import subprocess
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
    def run_case(self, body=None, args=None, error=None, token="fake-test-token",
                 signer=None):
        output = io.StringIO()
        calls = []

        def opener(request, timeout):
            calls.append(request)
            if error:
                raise error
            return Response(body)

        def fake_signer(body_bytes):
            return (claim.ENDPOINT + "?csecplatform=1&csecversion=test",
                    {"mtgsig": "fake-signature"})

        with tempfile.TemporaryDirectory() as directory:
            summary = os.path.join(directory, "summary.md")
            with patch.dict(os.environ, {"MEITUAN_PT_TOKEN": token,
                                        "MEITUAN_AI_SCENE": claim.DEFAULT_SCENE,
                                        "GITHUB_STEP_SUMMARY": summary}, clear=True):
                with contextlib.redirect_stdout(output):
                    result = claim.main(args or [], opener, signer or fake_signer)
            with open(summary, encoding="utf-8") as stream:
                summary_text = stream.read()
        return result, output.getvalue(), calls, summary_text

    def test_1014_is_failure_not_already_received(self):
        rc, log, calls, summary = self.run_case(b'{"code":1014,"msg":"rejected"}')
        self.assertEqual(rc, 1)
        self.assertIn("claim_rejected_reason_unknown", summary)
        self.assertNotIn("[SUCCESS]", log)
        self.assertEqual(len(calls), 1)

    def test_only_target_in_nonempty_coupon_list_is_success(self):
        for body, expected in [(b'{"code":200,"data":{"couponList":[{"priceLimit":4000,"couponValue":2000}]}}', 0),
                               (b'{"code":200,"data":{"couponList":[{}]}}', 1),
                               (b'{"code":200,"data":{"couponList":[]}}', 1),
                               (b'{"code":200,"data":{}}', 1),
                               (b'{"code":200,"data":{"couponList":[null]}}', 1),
                               (b'[]', 1), (b'{"code":401}', 1),
                               (b'{"code":509}', 1), (b'{"code":9999}', 1)]:
            with self.subTest(body=body):
                self.assertEqual(self.run_case(body)[0], expected)

    def test_config_check_never_sends_request(self):
        def unexpected_signer(body):
            self.fail("Configuration-only checks must not invoke the signer")

        rc, log, calls, summary = self.run_case(args=["--check-config"],
                                               signer=unexpected_signer)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertIn("token_sha256_16=", log)
        self.assertNotIn("fake-test-token", log + summary)

    def test_signs_and_sends_identical_compact_utf8_body(self):
        signed_bodies = []
        signed_url = claim.ENDPOINT + "?csecplatform=1&csecversion=test"

        def signer(body):
            signed_bodies.append(body)
            return signed_url, {"mtgsig": "fake-signature"}

        rc, log, calls, summary = self.run_case(
            b'{"code":200,"data":{"couponList":[{"priceLimit":4000,"couponValue":2000}]}}',
            token="fake-测试-token", signer=signer)
        expected = ('{"token":"fake-测试-token","aiScene":"' + claim.DEFAULT_SCENE
                    + '","version":2}').encode("utf-8")
        self.assertEqual(rc, 0)
        self.assertEqual(signed_bodies, [expected])
        self.assertEqual(len(calls), 1)
        request = calls[0]
        self.assertEqual(request.data, expected)
        self.assertEqual(request.full_url, signed_url)
        self.assertEqual(request.get_method(), "POST")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["mtgsig"], "fake-signature")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["x-requested-with"], "XMLHttpRequest")
        self.assertNotIn("fake-测试-token", log + summary)
        self.assertNotIn("fake-signature", log + summary)

    def test_signing_failure_never_sends_request_or_leaks_exception(self):
        def failed_signer(body):
            raise claim.SigningError("fake-test-token fake-signature")

        rc, log, calls, summary = self.run_case(signer=failed_signer)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])
        self.assertIn("signing_error_no_request", log + summary)
        self.assertNotIn("fake-test-token", log + summary)
        self.assertNotIn("fake-signature", log + summary)

    def test_request_check_signs_but_never_sends(self):
        signed_bodies = []

        def signer(body):
            signed_bodies.append(body)
            return (claim.ENDPOINT + "?csecplatform=1&csecversion=test",
                    {"mtgsig": "fake-signature"})

        rc, log, calls, summary = self.run_case(args=["--check-request"], signer=signer)
        self.assertEqual(rc, 0)
        self.assertEqual(len(signed_bodies), 1)
        self.assertEqual(calls, [])
        self.assertIn("signed_request_checked_only", summary)
        self.assertNotIn("[SUCCESS]", log)
        self.assertNotIn("fake-test-token", log + summary)
        self.assertNotIn("fake-signature", log + summary)

    def test_target_coupon_count_is_reported_without_coupon_details(self):
        coupons = [{"priceLimit": 4000, "couponValue": 2000,
                    "couponId": "private-coupon-id"},
                   {"priceLimit": "4000", "couponValue": "2000"},
                   {"priceLimit": 4000, "couponValue": 1000},
                   {"priceLimit": 5000, "couponValue": 2000}]
        rc, log, _, summary = self.run_case(
            json.dumps({"code": 200, "data": {"couponList": coupons}}).encode())
        outcome_line = next(line for line in log.splitlines() if line.startswith("[OUTCOME] "))
        outcome = json.loads(outcome_line.removeprefix("[OUTCOME] "))
        self.assertEqual(rc, 0)
        self.assertEqual(outcome["status"], "claimed")
        self.assertEqual(outcome["coupon_count"], 4)
        self.assertEqual(outcome["target_40_20_count"], 2)
        self.assertIn("满 40 减 20: 2", summary)
        self.assertNotIn("private-coupon-id", log + summary)

    def test_claimed_other_coupons_is_failure_for_target(self):
        rc, log, _, summary = self.run_case(
            b'{"code":200,"data":{"couponList":[{"priceLimit":5000,"couponValue":2000}]}}')
        self.assertEqual(rc, 1)
        self.assertIn("claimed_target_missing", log + summary)
        self.assertIn('"target_40_20_count": 0', log)
        self.assertIn("Confirmed coupons: 1", summary)
        self.assertIn("满 40 减 20: 0", summary)
        self.assertNotIn("[SUCCESS]", log)

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


class SignerBridgeTests(unittest.TestCase):
    def test_bridge_uses_stdin_for_body_and_returns_checked_request(self):
        body = b'{"token":"fake-test-token"}'
        signed_url = claim.ENDPOINT + "?csecplatform=1&csecversion=test"
        headers = {"mtgsig": "fake-signature"}
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"url": signed_url, "headers": headers}).encode(),
            stderr=b"")
        with patch.object(claim.subprocess, "run", return_value=completed) as run:
            self.assertEqual(claim.prepare_signed_request(body), (signed_url, headers))
        args, kwargs = run.call_args
        self.assertNotIn("fake-test-token", " ".join(args[0]))
        self.assertEqual(kwargs["input"], body)
        self.assertTrue(kwargs["capture_output"])

    def test_bridge_rejects_missing_signature_changed_endpoint_and_header_injection(self):
        valid_url = claim.ENDPOINT + "?csecplatform=1&csecversion=test"
        invalid_results = [
            {"url": valid_url, "headers": {}},
            {"url": valid_url, "headers": {"mtgsig": ""}},
            {"url": valid_url, "headers": {"mtgsig": "fake\r\nInjected: true"}},
            {"url": valid_url, "headers": {"mtgsig": "fake", "Cookie": "private"}},
            {"url": claim.ENDPOINT, "headers": {"mtgsig": "fake"}},
            {"url": "https://example.invalid/other?csecplatform=1&csecversion=test",
             "headers": {"mtgsig": "fake"}},
            {"url": valid_url + "#fragment", "headers": {"mtgsig": "fake"}},
        ]
        for prepared in invalid_results:
            with self.subTest(prepared=prepared):
                completed = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(prepared).encode(), stderr=b"")
                with patch.object(claim.subprocess, "run", return_value=completed):
                    with self.assertRaises(claim.SigningError):
                        claim.prepare_signed_request(b'{"token":"fake-test-token"}')

    def test_bridge_failure_does_not_expose_child_output(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"fake-test-token", stderr=b"fake-signature")
        with patch.object(claim.subprocess, "run", return_value=completed):
            with self.assertRaises(claim.SigningError) as raised:
                claim.prepare_signed_request(b'{"token":"fake-test-token"}')
        self.assertNotIn("fake-test-token", str(raised.exception))
        self.assertNotIn("fake-signature", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
