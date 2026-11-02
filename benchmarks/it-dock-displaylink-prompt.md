# IT troubleshooting: second monitor blank on a DisplayLink dock

A real case from 2026-10-28, used to test the `it-troubleshoot` profile's first reply.
Results are in [README.md](README.md#it-troubleshooting-displaylink-dock).

## Setup (hold these constant)

- A new chat on the `it-troubleshoot` profile, default workflow (Troubleshooting session).
- **No tools.** Turn the knowledge base off where it exists, so every engine has the same
  inputs.
- Attach Plugable's *USB Docking Stations Troubleshooting Guide* for the UD-ULTC4K (the
  short guide, not the full user manual). The vendor document is not stored here. Its
  first row for "There is no video on the monitor(s) attached to the dock" begins
  "Ensure that the software used by the device is installed and working in a good state"
  and, for macOS, points to the DisplayLink Manager App.
- Send the message below exactly as written, including its typo (`UD-ULTv4k`) and the
  ambiguous cable sentence. Real tickets read like this.
- Score only the first reply. Run each configuration 3 times (sampling makes single runs
  noisy) and record the harness commit from the run line.

## First message

```
I’m trying to setup a users MacBook Pro and it won’t pickup the 2nd monitor. It’s a M5 Pro so it supports 3 displays. It’s plugged into a dock Plugable UD-ULTv4k. Here is what I know so far:

1. One monitor extends the screen but the other shows blank. Reinserting the display port cable registers with the monitor since it exits sleep mode but no screen.
2. This a brand new setup for our new CFO
3. Dock is plugged to the MacBook over Thunderbolt 4, Dock has two monitors, two USB A to USB B from the monitors to the dock and Ethernet
4. macOS 27.2
```

## Answer key

The UD-ULTC4K is a DisplayLink dock. A Mac gets one display natively over the USB-C link;
every display beyond that needs the DisplayLink Manager driver, which also needs Screen &
System Audio Recording permission. The fix was installing DisplayLink Manager. The full
user manual says the dock "requires DisplayLink drivers for full functionality, especially
for multiple external displays". One working screen therefore says nothing about whether
the driver is installed. The USB-A to USB-B cables are the monitors' USB hubs; video is
DisplayPort.

## Scoring (yes/no per run)

1. DisplayLink Manager (installed and running) is the first check.
2. Ruled out lists only "none yet": no inference, even with a caveat, and no hypothesis
   dropped silently.
3. The reply quotes the guide's first "no video" step.
4. Product claims not in the conversation or the guide (dock design, permissions,
   compatibility, "known" behavior) are labeled unverified. A misread cable counts against
   this check.
