"""Offline regression tests; simulated BLE, no HA services or motor commands."""
import ast
import asyncio
import pathlib
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_upstream as baseline

ROOT = pathlib.Path(__file__).resolve().parents[1]
source = (ROOT / 'custom_components/hass_nuki_bt/status_reconnect.py').read_text()
tree = ast.parse(source)
tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
ns = dict(NukiDevice=baseline.namespace['OriginalMethods'], asyncio=asyncio,
          logging=baseline.logging, BleakError=baseline.BleakError, __name__='offline_fix',
          BleakClientWithServiceCache=object)
exec(compile(ast.fix_missing_locations(tree), 'status_reconnect', 'exec'), ns)
Fix = ns['StatusReconnectNukiDevice']
ns['_LOGGER'] = baseline.logger


class FixedFake(baseline.FakeDevice):
    _on_status_disconnect = Fix._on_status_disconnect

    def disconnect_event(self):
        super().disconnect_event()
        self._on_status_disconnect(self._client)


class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_connection_marker_is_per_lock(self):
        first, second = Fix.__new__(Fix), Fix.__new__(Fix)
        first._const = types.SimpleNamespace(StatusCode=types.SimpleNamespace(COMPLETED='COMPLETED'))
        with patch.object(baseline.namespace['OriginalMethods'], 'lock_action', AsyncMock(return_value=types.SimpleNamespace(status='COMPLETED')), create=True):
            await first.lock_action('synthetic')
        self.assertTrue(first._fresh_connection_for_state)
        self.assertFalse(getattr(second, '_fresh_connection_for_state', False))

    async def test_queued_state_read_after_motor_uses_fresh_connection(self):
        original_tree = ast.parse(baseline.SOURCE)
        original_class = next(n for n in original_tree.body if isinstance(n, ast.ClassDef) and n.name == 'NukiDevice')
        method = next(n for n in original_class.body if getattr(n, 'name', '') == 'lock_action')
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
        constants = types.SimpleNamespace(StatusCode=types.SimpleNamespace(ACCEPTED='ACCEPTED', COMPLETED='COMPLETED'))
        namespace = {**baseline.namespace, 'NukiConst':constants}
        exec(compile(ast.fix_missing_locations(module), 'original_lock_action', 'exec'), namespace)
        d = Fix.__new__(Fix)
        d._const = types.SimpleNamespace(StatusCode=constants.StatusCode, NukiCommand=types.SimpleNamespace(
            REQUEST_DATA='REQUEST_DATA', CHALLENGE='CHALLENGE', LOCK_ACTION='LOCK_ACTION', STATUS='STATUS', KEYTURNER_STATES='KEYTURNER_STATES'))
        d._operation_lock = asyncio.Lock()
        d._update_state_lock = asyncio.Lock()
        d._last_update_state_successful = False
        d._poll_needed_config = False
        d._app_id = 0
        d.last_state = {'config_update_count':1}
        d.config = {'synthetic':True}
        d._client = types.SimpleNamespace(is_connected=True)
        entered, release = asyncio.Event(), asyncio.Event()
        trace = []
        async def send(cmd, payload, *args, **kwargs):
            if cmd == 'LOCK_ACTION':
                trace.append('motor')
                entered.set()
                await release.wait()
                return types.SimpleNamespace(status='COMPLETED')
            if payload['command'] == 'CHALLENGE':
                trace.append('challenge')
                return types.SimpleNamespace(nonce=b'synthetic')
            self.assertFalse(d._client.is_connected)
            trace.append('state_read')
            return {'config_update_count':1}
        async def disconnect():
            self.assertTrue(d._operation_lock.locked())
            trace.append('disconnect')
            d._client.is_connected = False
        d.disconnect = disconnect
        with patch.object(baseline.namespace['OriginalMethods'], 'lock_action', namespace['lock_action'], create=True), patch.object(baseline.namespace['OriginalMethods'], '_send_encrypted_command', AsyncMock(side_effect=send), create=True):
            motor = asyncio.create_task(d.lock_action('synthetic', wait_for_completed=True))
            await entered.wait()
            status = asyncio.create_task(d.update_state())
            await asyncio.sleep(0)
            release.set()
            await asyncio.wait_for(asyncio.gather(motor, status), 1)
        self.assertEqual(trace, ['challenge','motor','disconnect','state_read'])
        self.assertFalse(d._fresh_connection_for_state)

    async def test_only_completed_motor_action_marks_next_state_read(self):
        for status, expected in [('COMPLETED', True), ('ACCEPTED', False)]:
            d = Fix.__new__(Fix)
            d._const = types.SimpleNamespace(StatusCode=types.SimpleNamespace(COMPLETED='COMPLETED'))
            result = types.SimpleNamespace(status=status)
            with patch.object(baseline.namespace['OriginalMethods'], 'lock_action', AsyncMock(return_value=result), create=True) as action:
                self.assertIs(await d.lock_action('synthetic', wait_for_completed=True), result)
                self.assertEqual(getattr(d, '_fresh_connection_for_state', False), expected)
                action.assert_awaited_once()

    async def test_fresh_connection_once_for_state_or_log_challenge(self):
        for first_read in ['KEYTURNER_STATES', 'CHALLENGE']:
            d = Fix.__new__(Fix)
            d._fresh_connection_for_state = True
            d._const = types.SimpleNamespace(NukiCommand=types.SimpleNamespace(REQUEST_DATA='REQUEST_DATA', KEYTURNER_STATES='KEYTURNER_STATES', CHALLENGE='CHALLENGE'))
            d._client = types.SimpleNamespace(is_connected=True)
            async def disconnect(): d._client.is_connected = False
            d.disconnect = AsyncMock(side_effect=disconnect)
            with patch.object(baseline.namespace['OriginalMethods'], '_send_encrypted_command', AsyncMock(return_value='ok'), create=True) as send:
                await d._send_encrypted_command('LOCK_ACTION', {})
                await d._send_encrypted_command('REQUEST_DATA', {'command':'PUBLIC_KEY'})
                d.disconnect.assert_not_awaited()
                self.assertTrue(d._fresh_connection_for_state)
                self.assertEqual(await d._send_encrypted_command('REQUEST_DATA', {'command':first_read}), 'ok')
                self.assertFalse(d._fresh_connection_for_state)
                await d._send_encrypted_command('REQUEST_DATA', {'command':'KEYTURNER_STATES'})
                d.disconnect.assert_awaited_once()
                self.assertEqual(send.await_count, 4)

    async def test_original_log_method_disconnects_before_challenge_once(self):
        original_tree = ast.parse(baseline.SOURCE)
        original_class = next(n for n in original_tree.body if isinstance(n, ast.ClassDef) and n.name == 'NukiDevice')
        method = next(n for n in original_class.body if getattr(n, 'name', '') == 'request_log_entries')
        module = ast.Module(body=[method], type_ignores=[])
        namespace = dict(baseline.namespace)
        exec(compile(ast.fix_missing_locations(module), 'original_log_method', 'exec'), namespace)
        d = Fix.__new__(Fix)
        d._fresh_connection_for_state = True
        d._const = types.SimpleNamespace(NukiCommand=types.SimpleNamespace(REQUEST_DATA='REQUEST_DATA', KEYTURNER_STATES='KEYTURNER_STATES', CHALLENGE='CHALLENGE', REQUEST_LOG_ENTRIES='REQUEST_LOG_ENTRIES', LOG_ENTRY='LOG_ENTRY', STATUS='STATUS'))
        d._client = types.SimpleNamespace(is_connected=True)
        d._operation_lock = asyncio.Lock()
        d._messages = []
        trace=[]
        async def disconnect():
            self.assertTrue(d._operation_lock.locked())
            trace.append('disconnect')
            d._client.is_connected = False
        d.disconnect = AsyncMock(side_effect=disconnect)
        async def send(cmd,payload,*args,**kwargs):
            trace.append(cmd)
            return types.SimpleNamespace(nonce=b'synthetic',status='COMPLETED')
        with patch.object(baseline.namespace['OriginalMethods'], '_send_encrypted_command', AsyncMock(side_effect=send), create=True):
            await namespace['request_log_entries'](d,security_pin=0)
            await namespace['request_log_entries'](d,security_pin=0)
        self.assertEqual(trace,['disconnect','REQUEST_DATA','REQUEST_LOG_ENTRIES','REQUEST_DATA','REQUEST_LOG_ENTRIES'])
        d.disconnect.assert_awaited_once()

    async def test_failed_disconnect_does_not_send_on_old_connection(self):
        d = Fix.__new__(Fix)
        d._fresh_connection_for_state = True
        d._const = types.SimpleNamespace(NukiCommand=types.SimpleNamespace(REQUEST_DATA='REQUEST_DATA', KEYTURNER_STATES='KEYTURNER_STATES', CHALLENGE='CHALLENGE'))
        d._client = types.SimpleNamespace(is_connected=True)
        d.disconnect = AsyncMock()
        with patch.object(baseline.namespace['OriginalMethods'], '_send_encrypted_command', AsyncMock(), create=True) as send:
            with self.assertRaises(baseline.BleakError):
                await d._send_encrypted_command('REQUEST_DATA', {'command':'KEYTURNER_STATES'})
            send.assert_not_awaited()
            self.assertTrue(d._fresh_connection_for_state)

    async def test_healthy_read_no_retry(self):
        d = FixedFake()
        await asyncio.wait_for(d.update_state(), .1)
        self.assertEqual(d.writes, 1)

    async def test_dropped_read_retries_before_original_timeout(self):
        d = FixedFake(drop=True)
        start = asyncio.get_running_loop().time()
        await asyncio.wait_for(d.update_state(), .15)
        self.assertLess(asyncio.get_running_loop().time() - start, .15)
        self.assertEqual(d.writes, 2)
        self.assertEqual(d.reconnects, 1)
        self.assertFalse(d._operation_lock.locked())

    async def test_repeated_disconnects_are_bounded(self):
        d = FixedFake()
        d.response_retry = 3
        async def write(*args, **kwargs):
            d.writes += 1
            asyncio.get_running_loop().call_later(.005, d.disconnect_event)
        d._client.write_gatt_char = write
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(d.update_state(), .15)
        self.assertEqual(d.writes, 3)
        self.assertFalse(d._operation_lock.locked())

    async def test_motor_and_challenge_waits_untouched(self):
        for expected in ['STATUS', 'CHALLENGE', None]:
            d = FixedFake()
            d._expected_response = expected
            d._notify_future = asyncio.get_running_loop().create_future()
            d.disconnect_event()
            self.assertFalse(d._notify_future.done())
            d._notify_future.cancel()

    async def test_old_client_and_connected_client_ignored(self):
        d = FixedFake()
        d._expected_response = 'KEYTURNER_STATES'
        d._notify_future = asyncio.get_running_loop().create_future()
        d._on_status_disconnect(types.SimpleNamespace(is_connected=False))
        d._on_status_disconnect(d._client)
        self.assertFalse(d._notify_future.done())
        d._notify_future.cancel()

    async def test_completed_or_absent_future_ignored(self):
        d = FixedFake()
        d._expected_response = 'KEYTURNER_STATES'
        d._notify_future = asyncio.get_running_loop().create_future()
        d._notify_future.set_result('done')
        d.disconnect_event()
        self.assertEqual(d._notify_future.result(), 'done')
        d._notify_future = None
        d.disconnect_event()

    async def test_connect_registers_callback_and_keeps_reuse(self):
        d = Fix.__new__(Fix)
        d._connect_lock = asyncio.Lock()
        d._ble_device = object()
        d._address = 'synthetic'
        d._client = None
        d._device_type = 'known'
        d._const = types.SimpleNamespace(BLE_PAIRING_CHAR='pair', BLE_CHAR='data')
        d._safe_start_notify = AsyncMock()
        d._notification_handler = object()
        client = types.SimpleNamespace(is_connected=True)
        establish = AsyncMock(return_value=client)
        ns['establish_connection'] = establish
        await d.connect()
        self.assertEqual(establish.call_args.kwargs['disconnected_callback'], d._on_status_disconnect)
        self.assertEqual(d._safe_start_notify.await_count, 2)
        await d.connect()
        self.assertEqual(establish.await_count, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
