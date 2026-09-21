"""Offline options/lifecycle tests; no HA instance, credentials, or BLE I/O."""
import ast
import copy
import importlib.util
import json
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/hass_nuki_bt"


class OptionsBase:
    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}


def compiled_node(path, name, namespace):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if getattr(n, "name", "") == name)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


class Tests(unittest.IsolatedAsyncioTestCase):
    def make_flow(self, options):
        ns = dict(config_entries=SimpleNamespace(OptionsFlow=OptionsBase), vol=vol,
                  CONF_STATUS_RECONNECT="status_reconnect", DEFAULT_STATUS_RECONNECT=False)
        cls = compiled_node(COMPONENT / "config_flow.py", "NukiOptionsFlow", ns)
        flow = cls()
        flow.config_entry = SimpleNamespace(options=options, data={"pairing": "synthetic"})
        return flow

    async def test_missing_option_is_disabled(self):
        flow = self.make_flow({})
        result = await flow.async_step_init()
        self.assertEqual(result["data_schema"]({}), {"status_reconnect": False})

    async def test_saved_true_is_shown_and_boolean_required(self):
        result = await self.make_flow({"status_reconnect": True}).async_step_init()
        self.assertEqual(result["data_schema"]({}), {"status_reconnect": True})
        with self.assertRaises(vol.Invalid):
            result["data_schema"]({"status_reconnect": "false"})

    async def test_save_preserves_other_options_and_pairing_data(self):
        flow = self.make_flow({"existing": 42, "status_reconnect": False})
        before = copy.deepcopy(flow.config_entry)
        result = await flow.async_step_init({"status_reconnect": True})
        self.assertEqual(result["data"], {"existing": 42, "status_reconnect": True})
        self.assertEqual(flow.config_entry, before)

    def test_class_selection_follows_option_not_identity(self):
        tree = ast.parse((COMPONENT / "__init__.py").read_text())
        setup = next(n for n in tree.body if getattr(n, "name", "") == "async_setup_entry")
        node = next(n for n in setup.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "device_class" for t in n.targets))
        original, recovery = object(), object()
        for options, expected in [({}, original), ({"status_reconnect": False}, original), ({"status_reconnect": True}, recovery)]:
            ns = dict(entry=SimpleNamespace(options=options), NukiDevice=original,
                      StatusReconnectNukiDevice=recovery, CONF_STATUS_RECONNECT="status_reconnect", DEFAULT_STATUS_RECONNECT=False)
            exec(compile(ast.Module(body=[node], type_ignores=[]), "selection", "exec"), ns)
            self.assertIs(ns["device_class"], expected)

    async def test_reload_uses_ha_manager(self):
        reload_entry = compiled_node(COMPONENT / "__init__.py", "async_reload_entry", {})
        manager = SimpleNamespace(async_reload=AsyncMock())
        await reload_entry(SimpleNamespace(config_entries=manager), SimpleNamespace(entry_id="synthetic"))
        manager.async_reload.assert_awaited_once_with("synthetic")

    async def test_unload_releases_connection_only_after_platform_success(self):
        for success in [True, False]:
            ns = dict(DOMAIN="hass_nuki_bt", PLATFORMS=[], BleakError=RuntimeError, _LOGGER=logging.getLogger(__name__))
            unload = compiled_node(COMPONENT / "__init__.py", "async_unload_entry", ns)
            device = SimpleNamespace(disconnect=AsyncMock())
            hass = SimpleNamespace(config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=success)),
                                   data={"hass_nuki_bt": {"synthetic": SimpleNamespace(device=device)}})
            self.assertEqual(await unload(hass, SimpleNamespace(entry_id="synthetic")), success)
            self.assertEqual(device.disconnect.await_count, int(success))
            self.assertEqual("synthetic" in hass.data["hass_nuki_bt"], not success)

    def test_manifest_keeps_domain_and_pinned_protocol(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], "hass_nuki_bt")
        self.assertEqual(manifest["requirements"], ["pyNukiBT==0.0.20"])
        tree = ast.parse((COMPONENT / "config_flow.py").read_text())
        cls = next(n for n in tree.body if getattr(n, "name", "") == "NukiFlowHandler")
        version = next(n.value.value for n in cls.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "VERSION" for t in n.targets))
        self.assertEqual(version, 1)

    def test_real_helper_imports_with_pinned_library(self):
        spec = importlib.util.spec_from_file_location("nuki_recovery_smoke", COMPONENT / "status_reconnect.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from pyNukiBT import NukiDevice
        self.assertTrue(issubclass(module.StatusReconnectNukiDevice, NukiDevice))


if __name__ == "__main__":
    unittest.main()
