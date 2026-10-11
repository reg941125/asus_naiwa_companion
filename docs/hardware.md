# Target hardware integration

Target: ASUS Tinker Board 3 (4 GB), UGen300 over USB 3.2 Gen 1 A-to-C,
powered USB hub for UVC camera, UAC microphone/speaker and serial I/O controller.
Provide ventilation for the compute base and a physical camera shutter.

This repository currently runs host workflows and simulated output. It does not
ship accelerator binaries or assert model compatibility. Validate the exact
UGen300/Hailo-10H SDK, drivers and licensed model artifacts on the target before
claiming working inference. Do not load arbitrary downloaded models into a demo.

| Adapter | Intended model | Required validation |
| --- | --- | --- |
| Presence and common object hints | YOLOv8n | HEF/build support, camera capture, confidence threshold, unknown state |
| Voice recognition | Whisper Base | Supported build, microphone capture, Mandarin/English command accuracy |
| Brief dialogue | Qwen2.5-1.5B-Instruct | Supported runtime, RAM budget, bounded context and output |
| On-demand scene questions | Qwen2-VL-2B-Instruct | Supported build and multimodal preprocessing |
| Host voice output | Piper + owned audio | Local Mandarin voice license, playback latency |

Use `ModelManager.run(adapter, request)` for blocking inference. Its lock permits
one inference at a time. Adapters must unload/release a model before returning
when switching workloads; that resource lifecycle is not supplied here. Resume
low-rate presence inference between speech and dialogue jobs. Timers run on the
host event loop, independently of inference. Map only exact recognized commands
through `VOICE_COMMANDS`; request confirmation for uncertainty. Never allow an
LLM, object cue or scene answer to invent or advance approved instructions.

Wire the physical mute input to `engine.muted` and suppress microphone capture at
the capture source. Wire shutter state to camera capture, and report unknown
presence while it is closed. Connect LED states to local engine status only.
These capture and serial drivers remain hardware integration work. Console
speech is the default; use `create_app(speaker=PiperSpeaker(model, output))` to
connect installed Piper and ALSA. Use a private, owned output path, remove it
after playback, and choose owned/licensed voices. This optional adapter writes
synthesized speech, not microphone recordings.

Acceptance on hardware: disconnect phone/internet during a timer; run inference
while a timer expires; test shutter and mute electrically; measure RAM, thermal
behavior and model-switch latency; verify no camera/audio/session egress with
packet capture; check power stability with all USB devices attached.
