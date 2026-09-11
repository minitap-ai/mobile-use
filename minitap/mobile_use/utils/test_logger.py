import logging

from minitap.mobile_use.utils.logger import MobileUseLogger


def test_exception_logs_the_active_traceback_without_raising(caplog):
    logger = MobileUseLogger(name="test-exception-logger", enable_file_logging=False)

    with caplog.at_level(logging.ERROR, logger="test-exception-logger"):
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("device command failed")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.message == "device command failed"
    assert record.exc_info is not None
    assert "ValueError: boom" in caplog.text
