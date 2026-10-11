# Milk Frog Companion

Local-first implementation of the AI Milk Frog proposal in
[Milk_Frog_Competition_For_Everyone_EN.pdf](Milk_Frog_Competition_For_Everyone_EN.pdf).
The Python device service controls approved study, cooking and supervised
workflow steps. A Flutter app pairs locally and sends commands. Optional pack
permissions use signed, device-bound offline entitlements.

## Run locally

Python 3.11+:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m scripts.simulate
python -m uvicorn milk_frog.device:create_app --factory --host 127.0.0.1 --port 8000
```

The pairing code appears on the **device console**, expires after five minutes,
and locks after five failed attempts. Pairing is single-use; restart the local
service for another physical pairing window. A new pairing revokes the previous
app token. State defaults to `data/device.sqlite`; set `MILK_FROG_DATA` to a
private device directory. Only one service worker may control a device.

For a phone, run with a device hostname and a TLS certificate trusted by the
phone (use a local CA or provisioned device certificate):

```sh
python -m uvicorn milk_frog.device:create_app --factory --host 0.0.0.0 --port 8443 --ssl-keyfile secrets/device.key --ssl-certfile secrets/device.crt
```

Bind the service only to the intended local network and restrict ingress to it.
The Flutter client requires HTTPS and never bypasses certificate validation.
Loopback HTTP above is for terminal development only. Example pairing:

```sh
curl -X POST http://127.0.0.1:8000/pair -H 'Content-Type: application/json' -d '{"code":"123456"}'
```

Use the returned token as `Authorization: Bearer TOKEN`. `/catalog` returns
static approved workflow definitions. `POST /commands` accepts `start` with
`workflow_id`, `confirm`, `pause`, `resume`, `stop`, `quiet` with `enabled`, or
`snooze` with `seconds`. Cooking and experiment starts additionally require
`permission_confirmed: true`. Successful commands return **204 with no session
payload**. Confirmation advances a step; an expired timer never does.

## Phone app

`app/lib/main.dart` and `app/pubspec.yaml` supply the Flutter UI. With a current
Flutter SDK installed, generate platform scaffolding, then run:

```sh
cd app
flutter create --empty --platforms android,ios .
flutter pub get
flutter analyze
flutter run
```

Ensure Android's main manifest has `android.permission.INTERNET` for release
builds; configure iOS local-network usage description and your private CA trust
on each platform. Pair using the physical code. Credentials use platform secure
storage. The app selects approved plans and sends controls; session feedback is
spoken locally. Flutter is not installed in the development environment used to
build this repository, so platform compilation remains to be verified.

Workflow JSON files live in `milk_frog/workflows/` and are included in Python packages.
`approved_by` records the local reviewer; demo labels are placeholders, not external approval.

## Included behavior

- Three illustrative demo workflows, validated JSON schema, explicit step confirmation,
  guarded mode switching and workspace permission confirmation.
- Multiple host timers, pause/resume, quiet mode, snooze and study absence reminders
  with a five-minute cooldown. Unknown presence never counts as absence.
- SQLite event/preferences storage; authenticated deletion stops the session,
  clears local records/entitlements and revokes pairing (device identity is retained).
- Serialized AI adapter manager that leaves host timers responsive.
- Ed25519 entitlement verification, device binding and expiry without cloud access.
- Account service factory that refuses purchases until real receipt verification
  and a signing key are supplied. No fake receipt approval or live billing.

The three demo plans are included for free. To require a pack, add `pack` to a
locally reviewed workflow. Set `MILK_FROG_ENTITLEMENT_PUBLIC_KEY` to the trusted
Ed25519 public key's raw bytes in hex, then send the signed entitlement to
`POST /entitlements`. The private signing key belongs only to the account
service. Receipt verification must validate store product and ownership,
revocation and replay before enabling purchases. The UI currently covers local
controls; account login and real store purchase UI are integration work.

## Privacy and limitations

Camera/audio capture, actual recognition/dialogue, accelerator model loading,
serial hardware controls and real purchases are adapter integration work, not
implemented capabilities. See [hardware integration](docs/hardware.md).
No raw camera or microphone recording is implemented. No endpoint exposes
session state, sensor data or local event history, and the device service makes
no outbound account/network requests. Static plans and entitlement acknowledgements
are the only app-visible data. Keep device logs private: console speech and
pairing codes are local output. SQLite contains local prompt/command events.

Host timers survive loss of app or internet. Process restart stops the session
and clears active timers; durable timer recovery and restart alerts remain
future work. Quiet mode suppresses speech, including timer alerts. Pausing freezes
all session timers; finishing steps leaves any outstanding timers running until
stop. Demo cooking uses no heat; the lab demo is a workspace checklist rather
than a chemical protocol. Replace demo content only after a responsible reviewer
approves the actual workflow. No licensed character art or model weights are
included.
