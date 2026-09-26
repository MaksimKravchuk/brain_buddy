# Offline macOS POC check — 2026-09-26

## Conditions

- MacBook Air (Mac16,12), Apple M4, 16 GB, macOS 26.5.2.
- Built `BrainBuddyMac.app` from application source at `7204024` with
  `sh build_app.sh` and launched its executable through
  `sandbox-exec -p '(version 1) (allow default) (deny network*)'`.
  The network restriction applied only to the test process.
- The local Application Support store did not exist before each live run.
  Test-only data was inspected and removed after the runs.
- After the Waiting for lifecycle correction, rebuilt and relaunched the app
  under the same process-level network restriction for a focused closure check.
- On source commit `b4710e8`, relaunched the rebuilt app with the same network
  restriction for a focused microphone and Whisper check.

## Observed in the running app

| Journey | Observation under network denial |
| --- | --- |
| Launch | Opened directly to Next actions with “On this Mac”; no web sign-in. |
| Capture and edit | Created a task, project, and tag; saved description and tag on a project task. |
| Project archive | Archived and restored the project; its task kept project membership. The archive view did not offer Add task, and toolbar New task opened Next actions. |
| Restart | After stopping and relaunching under the same network rule, project, both tasks, tag, description, and classification were still present. |
| Task lifecycle | Created a task, completed it, then reopened it into Next actions. |
| Waiting for | Created a Waiting for task with `Insurer`; after another offline restart, both the reopened task and Waiting for target were present. |
| Waiting for closure | Completed a Waiting for task under network denial. The local snapshot retained its `lastOpenState` but contained neither `waitingFor` nor `waitingSince`; after an offline restart, the task appeared in Completed. |
| Voice capture | Recorded a short ambient sample from the microphone, then used Stop & transcribe. The bundled local model loaded and returned an editable transcript (`[музыка]`) while the app process had no network access. Closed the sheet without creating a task; no temporary WAV or task store remained. This checks the offline path, not speech accuracy. |

## Additional local interaction checks

- After switching the app to a single `Window` scene, the rebuilt app exposed
  one `main` window and no New Window command in its Window menu.
- In the rebuilt app, typed a Waiting for draft with `Insurer`, then selected
  Next actions. The app asked before changing context. Keep editing retained
  both fields; Discard changes cleared them before opening Next actions. This
  check used the local app with network available to its process; it did not
  exercise a web request or create a Task.

The macOS package's 49 Swift tests passed, including atomic local persistence,
failed-write and corrupt-file protection, idempotent replay and changed-payload
rejection after restart, protection from a stale second store, project Inbox
capture, archive membership across all task states, sidebar counts, and
Waiting for completion/reopen after restart.

## Limits

- This was a local POC check, not a production deployment or synchronization test.
- Voice transcription was also exercised separately with a local synthetic
  Russian WAV. The live microphone run above used only ambient sound, so it
  does not establish transcription accuracy for spoken tasks.
- Automatic multi-task extraction remains deferred; see
  [local extraction feasibility](local-extraction-feasibility.md).
- Repository-wide `make verify-all` stopped at the existing modified
  `specs/019-macos-native-gtd` artifact set because `tasks.md` is missing.
