"""Regression reproduction using pinned upstream methods and simulated BLE."""
import ast
import asyncio
import hashlib
import json
import logging
import types
import unittest

from importlib.metadata import distribution, version
from pathlib import Path

assert version("pyNukiBT") == "0.0.20", "Revalidate copied connect logic before upgrading"
SOURCE = Path(distribution("pyNukiBT").locate_file("pyNukiBT/nuki.py")).read_text()
tree = ast.parse(SOURCE)
device_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "NukiDevice")
methods = [n for n in device_class.body if getattr(n, "name", "") in {"_send_command", "update_state"}]
module = ast.Module(body=[
    ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
    ast.ClassDef(name="OriginalMethods", bases=[], keywords=[], body=methods, decorator_list=[]),
], type_ignores=[])
logger = logging.getLogger("offline-nuki-test")
logger.addHandler(logging.NullHandler())
logger.propagate = False


class BleakError(Exception):
    pass


namespace = dict(asyncio=asyncio, logger=logger, BleakError=BleakError,
                 CancelledError=asyncio.CancelledError, TimeoutError=TimeoutError,
                 async_timeout=types.SimpleNamespace(timeout=asyncio.timeout))
exec(compile(ast.fix_missing_locations(module), "installed_nuki_methods", "exec"), namespace)


class FakeDevice(namespace["OriginalMethods"]):
    def __init__(self, drop=False):
        self.drop = drop
        self.writes = 0
        self.reconnects = 0
        self.dropped = asyncio.Event()
        self._send_cmd_lock = asyncio.Lock()
        self._update_state_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._last_update_state_successful = False
        self._poll_needed_config = False
        self.config = {"synthetic": True}
        self.last_state = {"config_update_count": 1}
        self.response_retry = 2
        self.send_retry = 1
        self.retry_interval = 0.001
        self.command_response_timeout = 0.25
        self._const = types.SimpleNamespace(NukiCommand=types.SimpleNamespace(
            REQUEST_DATA="REQUEST_DATA", KEYTURNER_STATES="KEYTURNER_STATES"))
        self._client = types.SimpleNamespace(is_connected=True, write_gatt_char=self.write)

    async def connect(self):
        if not self._client.is_connected:
            self.reconnects += 1
            self._client.is_connected = True

    async def _send_encrypted_command(self, command, payload, expected_response):
        return await self._send_command("synthetic", b"", expected_response=expected_response)

    async def write(self, characteristic, command, response):
        self.writes += 1
        if self.drop and self.writes == 1:
            asyncio.get_running_loop().call_later(0.02, self.disconnect_event)
        else:
            self._notify_future.set_result({"config_update_count": 1})

    def disconnect_event(self):
        self._client.is_connected = False
        self.dropped.set()


class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_status_releases_operation_lock(self):
        d = FakeDevice()
        await asyncio.wait_for(d.update_state(), 0.1)
        self.assertFalse(d._operation_lock.locked())
        self.assertEqual(d.writes, 1)

    async def test_disconnect_leaves_waiter_blocked_until_timeout(self):
        d = FakeDevice(drop=True)
        start = asyncio.get_running_loop().time()
        update = asyncio.create_task(d.update_state())
        await asyncio.wait_for(d.dropped.wait(), 0.1)
        self.assertFalse(d._client.is_connected)
        self.assertFalse(d._notify_future.done())
        self.assertTrue(d._operation_lock.locked())
        acquired = asyncio.Event()

        async def subsequent_operation():
            async with d._operation_lock:
                acquired.set()

        waiter = asyncio.create_task(subsequent_operation())
        await asyncio.sleep(0.08)
        self.assertFalse(acquired.is_set())
        self.assertEqual(d.reconnects, 0)
        await asyncio.wait_for(asyncio.gather(update, waiter), 1)
        elapsed = asyncio.get_running_loop().time() - start
        self.assertGreaterEqual(elapsed, 0.25)
        self.assertEqual(d.reconnects, 1)
        self.assertEqual(d.writes, 2)
        print(json.dumps({"scenario": "simulated_disconnect", "configured_timeout_s": 0.25,
                          "next_operation_after_s": round(elapsed, 3), "reconnects": d.reconnects}))

    def test_no_disconnect_callback_registered(self):
        connect = next(n for n in device_class.body if getattr(n, "name", "") == "connect")
        call = next(n for n in ast.walk(connect) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "establish_connection")
        self.assertEqual(len(call.args), 3)
        self.assertNotIn("disconnected_callback", [kw.arg for kw in call.keywords])


if __name__ == "__main__":
    print(json.dumps({"source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
                      "scope": "offline; no BLE, no service calls, no production changes"}))
    unittest.main(verbosity=2)
