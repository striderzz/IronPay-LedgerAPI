import json
import logging

from app.logging_setup import JsonFormatter
from app.request_context import request_id_var


def test_json_formatter_adds_request_id_and_fields():
    token = request_id_var.set("req-1")
    try:
        record = logging.LogRecord("ironpay", logging.INFO, __file__, 1, "hello %s", ("x",), None)
        record.fields = {"status": 201}
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["msg"] == "hello x"
    assert line["request_id"] == "req-1"
    assert line["status"] == 201
    assert line["level"] == "INFO"
