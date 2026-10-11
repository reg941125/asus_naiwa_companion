# Testing without the physical device

The software test suite runs on a laptop or CI runner, without the Tinker Board,
UGen300, camera, microphone or speaker. No store account or external service is
required by these tests. Dependency installation requires internet access.

## Python

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

29 tests cover:

- Step confirmation, pause/resume, multiple timers, absence cooldown, snooze and quiet mode.
- Pairing expiry/lockout, authentication, entitlement signatures, device binding and expiry.
- Restart persistence, token rotation, deletion across restart and fail-closed workflow validation.
- Inference serialization, single and repeated cancellation, adapter failure recovery.
- Blocked or disconnected voice output, and temporary synthesized-audio cleanup.
- An actual Uvicorn child process serving HTTPS with a temporary test certificate.
- Certificate trust rejection, concurrent authenticated requests and confirmations,
  payload rejection, and timer completion while no phone requests are made.

HTTPS tests bind only to loopback, generate their own certificate and temporary
SQLite directory, start their own subprocess, and stop it after the tests. Test
output can include deliberately simulated speaker failures; the unittest result
is the authoritative pass/fail status.

## Flutter

With Flutter installed:

```sh
cd app
flutter create --empty --platforms android,ios .
flutter pub get
flutter analyze
flutter test
```

Six widget tests use a mock HTTP client and mock platform secure storage. They
check pairing and credential storage, HTTPS-origin validation, pairing errors,
command payloads and quiet toggles, recovery from an offline saved connection,
and cancel/confirm behavior for local-data deletion.

Local validation on 2026-10-11 used Python 3.14 and Flutter 3.47.7 / Dart 3.13.5.
The Python wheel was also installed into a separate temporary target; startup,
pairing and all three packaged workflows worked from that installation.
GitHub Actions repeats Python checks on 3.11 and 3.14, plus Flutter analysis and
widget tests.

The expanded suite discovered a repeated-cancellation bug that could release the
model lock before an inference thread finished; the manager now retains the lock
until the worker exits. The original Flutter CI analysis failure was caused by a
missing `flutter_lints` dependency; it is now declared.

## What passing tests establish

Passing tests establish host software behavior and Flutter UI behavior with
mocked network/storage. They do not establish accelerator model compatibility,
physical mute/shutter behavior, thermals, audio accuracy, Android/iOS release
builds, installed-app certificate handling or real store receipt verification.

A GitHub push publishes source, and GitHub Actions verifies software. The current
workflow does **not** deploy or keep a service running. To run the host, follow
the Uvicorn/TLS instructions in the root README. A physical deployment still
requires the hardware acceptance checks in `hardware.md`. Active sessions and
timers do not survive host-process restart; saved credentials/preferences do.
