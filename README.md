# Nuki BT

## Connection-recovery fork

This is a small compatibility fork of [ronengr/hass_nuki_bt](https://github.com/ronengr/hass_nuki_bt), based on upstream 0.0.20.
The integration domain remains `hass_nuki_bt`; existing config entries,
pairing credentials and entity identities are retained. Do not delete your
configured locks or pair them again when switching code sources.

### Optional Bluetooth recovery

Under **Settings > Devices & services > Nuki BT > Configure**, enable
**status and post-action connection recovery** for each affected lock.
It is disabled by default and changing it reloads only that device.
Other options and pairing data are preserved.

The workaround immediately releases a pending state-response wait when its
BLE client disconnects, using the library's existing bounded read retry.
After a confirmed completed motor command, the first state read or challenge
request uses a fresh connection. It adds no motor-command retries, does not
shorten global timeouts, and leaves event-log retrieval enabled.

This is an experimental workaround, not a guarantee against RF interference,
proxy congestion or lock firmware issues. It has been tested with Smart Locks
and Bluetooth proxies; other device types, including Openers, have not been
hardware-validated. Keep `pyNukiBT==0.0.20`: the connection override mirrors
that version and must be reviewed before upgrading the library.

### Switching from upstream without pairing again

1. Make and verify a protected Home Assistant backup, including `.storage`
   and `custom_components/hass_nuki_bt`. The backup contains credentials;
   never upload it to an issue or this repository.
2. Remove the upstream **repository download in HACS**, not the configured
   integration entries under Devices & services. Do not revoke lock access.
3. Add `https://github.com/evgparen/hass_nuki_bt` as a custom HACS repository
   of type Integration and download a tagged release. Only one repository
   may manage this component directory. Do not restart between removal and
   installation; restore the old code if installation fails.
4. Restart Home Assistant, enable the recovery option on affected locks,
   and verify status/log retrieval, entity IDs and lock operation.

Rollback replaces only component code and its HACS source; keep the existing
HA entries and lock permissions. Do not restore an entire HA configuration
over newer unrelated changes merely to roll back this code.

### Development

Use Python 3.14 and run `python -m pip install -r requirements-test.txt`,
then `python -m unittest discover -s tests -v`.
Tests simulate BLE and extract unmodified methods from the pinned upstream
library. They do not contact Home Assistant or operate physical locks.
Test data is synthetic. Never commit real addresses, pairing keys or PINs.
Release tags and `manifest.json` versions must match. The release workflow
runs tests and publishes the `hass_nuki_bt.zip` asset consumed by HACS.

Original project documentation follows. For this fork, use the repository URL
above rather than the upstream installation URL below.

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]

[![Community Forum][forum-shield]][forum]

Nuki lock integration for Home Assistant.
This integration communicates directly with Nuki over Bluetooth. No need for a bridge.


## Background
- This project is based on [RaspiNukiBridge](https://github.com/regevbr/RaspiNukiBridge) by [dauden1184](https://github.com/dauden1184/) and [regevbr](https://github.com/regevbr)
- This project is heavily inspired by [kvj](https://github.com/kvj)'s [hass_nuki_ng](https://github.com/kvj/hass_nuki_ng) and [technyon](https://github.com/technyon)'s [nuki_hub](https://github.com/technyon/nuki_hub)

## Setup

{% if not installed %}

### Installation:
* Go to HACS -> Integrations
* Click the three dots on the top right and select `Custom Repositories`
* Enter `https://github.com/ronengr/hass_nuki_bt` as repository, select the category `Integration` and click Add
* A new custom integration shows up for installation (Nuki BT) - install it
* Restart Home Assistant

{% endif %}

### Configuration:
* Go to Settings -> Devices & Services
* The integration should automatically discover your Nuki lock. You Should see a new Discovered Device, just click on "Configure" to configure it.
  * If no look was discovered, and you know the Nuki's BT address, you can try to add it manually by clicking on "Add Integration"
* Select a Device Name and Client Type
* Enable pairing mode on the Nuki lock by holding down the button on the Nuki Smart Lock for 5 seconds until the LED ring is permanently glowing.
* Select "Pair device automatically"
  * It is possible to configure the device manually, if you have the pairing-information from an already paired device.
    Use this option only if you know what you are doing. This is mostly meant for development.

#### Client Type:
hass_nuki_bt can connect to the Nuki lock in 2 ways:
  * "Bridge" is the recommended way. This will cause the current Bridge to be unregistered when pairing.
  * "App" will allow you to run hass_nuki_bt alongside a Nuki Bridge, but can lead to either device missing updates.


## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

Latest Nuki Bluetooth API spec: https://developer.nuki.io/t/bluetooth-api/27

***

[hass_nuki_bt]: https://github.com/ronengr/hass_nuki_bt
[commits-shield]: https://img.shields.io/github/commit-activity/y/ronengr/hass_nuki_bt.svg?style=for-the-badge
[commits]: https://github.com/ronengr/hass_nuki_bt/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[exampleimg]: example.png
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/ronengr/hass_nuki_bt.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%20%40ronengr-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/ronengr/hass_nuki_bt.svg?style=for-the-badge
[releases]: https://github.com/ronengr/hass_nuki_bt/releases
