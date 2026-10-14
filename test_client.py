"""Offline contract and credential-boundary tests. No API requests."""

import copy
import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

import easydown_api_client as sdk

URL = "https://www.tiktok.com/@fixture/video/123"
TOKEN = "offline-test-token"


def media():
    return {
        "platform": "tiktok", "title": "Test", "thumbnail": "https://example.com/thumb",
        "duration": 1234, "images": [
            {"url": "https://example.com/2.jpg", "width": 720, "height": 1280},
            {"url": "https://example.com/1.jpg", "width": 720, "height": 1280},
        ], "videos": [{
            "url": "https://example.com/video", "quality": "720p", "mimeType": "video/mp4",
            "width": 720, "height": 1280, "hasAudio": True, "source": "direct",
            "headers": {"Referer": "https://example.com"},
        }], "audios": [{
            "url": "https://example.com/audio", "quality": "128k", "mimeType": "audio/mpeg",
            "bitrate": 128000, "source": "native_voice",
        }],
    }


def response(data=None, status=200, msg="success", code=None):
    body = {"status": status, "msg": msg, "data": media() if data is None else data}
    if code is not None:
        body["code"] = code
    return sdk.HttpResponse(200, json.dumps(body).encode())


class ClientTests(unittest.TestCase):
    def test_import_and_construct_do_not_call_transport(self):
        transport = MagicMock()
        sdk.EasyDownClient(TOKEN, transport=transport)
        transport.assert_not_called()

    def test_unified_request_and_media_order(self):
        transport = MagicMock(return_value=response())
        result = sdk.EasyDownClient(TOKEN, timeout=12, transport=transport).parse(URL)
        request, timeout = transport.call_args.args
        self.assertEqual(request.full_url, "https://api.easydown.org/api/v1/parse")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertIsNone(request.get_header("Cookie"))
        self.assertEqual(json.loads(request.data), {"url": URL})
        self.assertEqual(timeout, 12.0)
        self.assertEqual(result["duration"], 1234)
        self.assertEqual([i["url"] for i in result["images"]],
                         ["https://example.com/2.jpg", "https://example.com/1.jpg"])

    def test_platform_envelope_preserves_unknown_fields(self):
        payload = {"media": media(), "platformData": {"future": [1, {"nested": True}]},
                   "platformDataVersion": "1"}
        transport = MagicMock(return_value=response(payload))
        result = sdk.EasyDownClient(TOKEN, transport=transport).parse_platform("tiktok", URL)
        self.assertEqual(result, payload)
        self.assertEqual(transport.call_args.args[0].full_url,
                         "https://api.easydown.org/api/v1/platforms/tiktok/parse")

    def test_all_documented_platform_paths(self):
        for platform in sdk.PLATFORMS:
            with self.subTest(platform=platform):
                value = media()
                value["platform"] = platform
                transport = MagicMock(return_value=response({
                    "media": value, "platformData": {}, "platformDataVersion": "1"}))
                sdk.EasyDownClient(TOKEN, transport=transport).parse_platform(platform, URL)
                self.assertTrue(transport.call_args.args[0].full_url.endswith(
                    f"/platforms/{platform}/parse"))

    def test_invalid_local_inputs_never_call_transport(self):
        transport = MagicMock()
        client = sdk.EasyDownClient(TOKEN, transport=transport)
        for url in (None, "", "file:///tmp/a", "https://user:secret@example.com/a",
                    "https://", "https://example.com:bad/a", "https://example.com/a\n"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.parse(url)
        for platform in ("x", "rednote", "../x", None, []):
            with self.subTest(platform=platform), self.assertRaises(ValueError):
                client.parse_platform(platform, URL)
        transport.assert_not_called()

    def test_invalid_constructor_inputs(self):
        for token in (None, "", "  ", "token\r\n", "token\x7f", "令牌"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                sdk.EasyDownClient(token)
        for timeout in (0, -1, True, "1", float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                sdk.EasyDownClient(TOKEN, timeout=timeout)
        with self.assertRaises(TypeError):
            sdk.EasyDownClient(TOKEN, transport=123)

    def test_client_repr_redacts_token(self):
        self.assertNotIn(TOKEN, repr(sdk.EasyDownClient(TOKEN)))

    def assert_failure(self, transport, kind, status=None):
        with self.assertRaises(sdk.EasyDownError) as caught:
            sdk.EasyDownClient(TOKEN, transport=transport).parse(URL)
        error = caught.exception
        self.assertEqual((error.kind, error.http_status), (kind, status))
        self.assertNotIn(TOKEN, str(error))
        self.assertNotIn(URL, str(error))
        transport.assert_called_once()
        return error

    def test_unsuccessful_http_statuses_and_no_retry(self):
        for status in (302, 400, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.assert_failure(MagicMock(return_value=sdk.HttpResponse(
                    status, (TOKEN + URL).encode())), "http", status)

    def test_api_code_is_safe_and_raw_message_is_omitted(self):
        error = self.assert_failure(MagicMock(return_value=response(
            status=403, msg=TOKEN + URL, code="insufficient_credits")), "api", 200)
        self.assertEqual(error.code, "insufficient_credits")
        for code in (TOKEN, {"secret": TOKEN}):
            error = self.assert_failure(MagicMock(return_value=response(
                status=500, code=code)), "api", 200)
            self.assertIsNone(error.code)

    def test_invalid_json_and_response_envelopes(self):
        for body in (b"not json", b"\xff", b"[]", b"null", b"{}",
                     b'{"status":true}', b'{"status":NaN}', b'{"status":200,"data":{}}',
                     b'{"status":200,"msg":"success","data":null}'):
            with self.subTest(body=body):
                self.assert_failure(MagicMock(return_value=sdk.HttpResponse(200, body)),
                                    "invalid_response", 200)

    def test_missing_or_wrong_media_fields(self):
        malformed = []
        for field in media():
            value = media()
            del value[field]
            malformed.append(value)
        value = media(); value["duration"] = True; malformed.append(value)
        value = media(); value["images"][0]["width"] = "720"; malformed.append(value)
        value = media(); value["videos"][0]["hasAudio"] = 1; malformed.append(value)
        value = media(); value["videos"][0]["headers"] = {"bad": 123}; malformed.append(value)
        value = media(); value["audios"][0]["source"] = "unknown"; malformed.append(value)
        for value in malformed:
            with self.subTest(value=value):
                self.assert_failure(MagicMock(return_value=response(value)),
                                    "invalid_response", 200)

    def test_wrong_platform_or_platform_envelope(self):
        original = {"media": media(), "platformData": {}, "platformDataVersion": "1"}
        malformed = []
        for field in original:
            value = copy.deepcopy(original); del value[field]; malformed.append(value)
        value = copy.deepcopy(original); value["media"]["platform"] = "instagram"; malformed.append(value)
        value = copy.deepcopy(original); value["platformData"] = []; malformed.append(value)
        for value in malformed:
            transport = MagicMock(return_value=response(value))
            with self.subTest(value=value), self.assertRaises(sdk.EasyDownError) as caught:
                sdk.EasyDownClient(TOKEN, transport=transport).parse_platform("tiktok", URL)
            self.assertEqual(caught.exception.kind, "invalid_response")

    def test_oversized_or_wrong_transport_response(self):
        self.assert_failure(MagicMock(return_value=sdk.HttpResponse(
            200, b"x" * (sdk._MAX_RESPONSE_BYTES + 1))), "invalid_response", 200)
        for value in (None, sdk.HttpResponse(True, b"{}"), sdk.HttpResponse(200, "{}")):
            self.assert_failure(MagicMock(return_value=value), "invalid_response")

    def test_timeout_and_network_error_omit_raw_exception(self):
        for error, kind in ((TimeoutError(TOKEN + URL), "timeout"),
                            (RuntimeError(TOKEN + URL), "network")):
            caught = self.assert_failure(MagicMock(side_effect=error), kind)
            self.assertTrue(caught.__suppress_context__)

    def test_default_transport_blocks_redirects(self):
        with patch.object(sdk, "build_opener") as factory:
            factory.return_value.open.side_effect = HTTPError(
                URL, 302, "Redirect", {"Location": "https://example.com"}, io.BytesIO())
            with self.assertRaises(sdk.EasyDownError) as caught:
                sdk.EasyDownClient(TOKEN).parse(URL)
            handler = factory.call_args.args[0]
            self.assertIsInstance(handler, sdk._NoRedirect)
            self.assertIsNone(handler.redirect_request(Request(URL), None, 302, "", {}, URL))
            self.assertEqual((caught.exception.kind, caught.exception.http_status), ("http", 302))
            factory.return_value.open.assert_called_once()

    def test_default_transport_socket_failure_classification(self):
        for error, kind in ((URLError(TimeoutError()), "timeout"),
                            (URLError(TOKEN), "network")):
            with patch.object(sdk, "build_opener") as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaises(sdk.EasyDownError) as caught:
                    sdk.EasyDownClient(TOKEN).parse(URL)
                self.assertEqual(caught.exception.kind, kind)

    def test_default_transport_reads_with_size_limit(self):
        with patch.object(sdk, "build_opener") as factory:
            reply = factory.return_value.open.return_value.__enter__.return_value
            reply.status = 200
            reply.read.return_value = response().body
            self.assertEqual(sdk.EasyDownClient(TOKEN).parse(URL), media())
            reply.read.assert_called_once_with(sdk._MAX_RESPONSE_BYTES + 1)


if __name__ == "__main__":
    unittest.main()
