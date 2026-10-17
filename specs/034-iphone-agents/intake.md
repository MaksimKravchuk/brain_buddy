# Intake: iPhone agents

**Feature**: `034-iphone-agents` · **Created**: 2026-10-16 · **Owner**: Max (product owner)

## The ask, as given

Max (2026-10-16, project thread "Carry On на iOS"): hand the canvas screens that need new iPhone
features to agents and build them. This feature is the agents group: canvas screens **21 Hand off,
22 Agent runs, 23 Needs you, 24 Result, 29 Agent details and 30 Add agent**, iPhone row
(canvas https://claude.ai/artifact/1bwKiw15U2jpZqwu5pTMg6, version `1792165683-83f3`).

## Interview

No new interview was held. The behaviour is the Mac's, decided with Max in the 030 interview
(decisions D1 – D9 in [030 intake](../030-mac-agents/intake.md#interview-2026-10-16)) and
delivered in `specs/030-mac-agents`. Standing rules from Max that apply here: match the canvas
exactly (colours too), do not invent behaviour, decide reversible things without waiting, and
ask only on irreversible steps.

## 1. Problem

The server relays steps to the owner's external agents (specs 007, 014) and the web and the Mac
show it. The iPhone, the platform Max puts first, shows nothing: a step handed off elsewhere sits
in the phone's lists with no sign that an agent is working on it or waiting for an answer.

## 2. Customer and persona

The single owner of an account who has connected at least one agent on the web or the Mac and
captures and reviews steps mostly on the phone.

## 3. Business objective

Parity with the Mac for the agent loop on the phone: see what agents are doing, answer a
question, accept or reject a result, hand a step off, and manage agents, without opening the web.

## 4. Scope boundary

In: the six canvas screens above on iPhone, against the existing relay API and the Mac's
models. Out: All runs canvas and the sidebar (the iPhone has neither; runs live in Waiting for),
push notifications (polling only, D7), any backend change, the account screens 26 – 28
(feature 033), voice (031), first run (032).

## 5. Constraints

- No backend change (030-FR-042 holds here too).
- One implementation of the rules for both apps: the iPhone reuses the Mac's 030 models, moved
  into the shared kit, rather than a second copy.
- Swift 6 strict concurrency, iOS 26, no third-party dependency, Carry On components only.

## 6. Compliance obligation

As 030: agent content and secrets live in memory only, are dropped on sign-out and account change,
respect the 30-day content expiry, and never reach a log.

## 7. Existing-system dependencies

`BrainBuddyAPI` agent connections and runs (030 PR-01, PR-02), `Workspace.openStepServerIDs()`
(030 PR-15), the Mac models in `macos/Sources/BrainBuddyMacCore/` (030 PR-03 – PR-06, PR-14),
the iPhone's Waiting for list, task card and Settings screen.

## 8. Definition of done

Every screen built and wired, the kit tests green on Linux and macOS, the `ios-app` and Mac lanes
green, review threads resolved, PRs merged through the queue.
