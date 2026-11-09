# IT troubleshooting: Intune rename fails with "The RPC server is unavailable"

A real case from 2026-11-04, used to test the `it-troubleshoot` profile's first reply when
the model must reason from a pasted log. Results are in
[README.md](README.md#it-troubleshooting-intune-rename-rpc-error).

The domain name and serial numbers are replaced with stand-ins. The letter case of the
placeholder name is kept, because the mixed-case versus all-caps difference is part of the log.

## Setup (hold these constant)

- A new chat on the `it-troubleshoot` profile, default workflow (Troubleshooting session).
- **No tools** for the baseline: turn the knowledge base off where it exists. A second
  configuration, once the LJA `it` collection exists, runs the same message with the
  rename-script runbook loaded, to measure what the knowledge base adds.
- Send the message below exactly as written, including the `PRC` typo.
- Score only the first reply. Run each configuration 3 times and record the harness commit
  from the run line.

## First message

```
What is a RPC server in reference to Active Directory or Azure? We have a computer that failed the renaming process and that was the error. We provision them through Intune and have a script that connects through the domain controller to ADManager plus (our on-prem AD) and it names it LJA- (the serial number). I have never seen the PRC server error before

**********************
Windows PowerShell transcript start
Start time: 20261104122253
Username: CORPDOM\SYSTEM
RunAs User: CORPDOM\SYSTEM
Configuration Name: 
Machine: LJA-7QKXRB3M9TZ (Microsoft Windows NT 10.0.26100.0)
Host Application: C:\Windows\SysNative\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy bypass -File C:\Windows\IMECache\9c8de000-9d3a-428a-ad48-1f09f6b68ac5_2\RenameComputer.ps1
Process ID: 5996
PSVersion: 5.1.26100.9711
PSEdition: Desktop
PSCompatibleVersions: 1.0, 2.0, 3.0, 4.0, 5.0, 5.1.26100.9711
BuildVersion: 10.0.26100.9711
CLRVersion: 4.0.30319.42000
WSManStackVersion: 3.0
PSRemotingProtocolVersion: 2.3
SerializationVersion: 1.1.0.1
**********************
Transcript started, output file is C:\ProgramData\Microsoft\RenameComputer\RenameComputer.log
Renaming computer to LJA-5HT82047KC
Rename-Computer : Fail to rename computer 'LJA-7QKxRb3m9TZ' to 'LJA-5HT82047KC' due to the following exception: The RPC 
server is unavailable.
At C:\Windows\IMECache\9c8de000-9d3a-428a-ad48-1f09f6b68ac5_2\RenameComputer.ps1:101 char:5
+     Rename-Computer -NewName $newName
+     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (LJA-7QKxRb3m9TZ:String) [Rename-Computer], InvalidOperationException
    + FullyQualifiedErrorId : FailToRenameComputer,Microsoft.PowerShell.Commands.RenameComputerCommand
Rename-Computer : Fail to rename computer 'LJA-7QKxRb3m9TZ' to 'LJA-5HT82047KC' due to the following exception: The
RPC server is unavailable.
At C:\Windows\IMECache\9c8de000-9d3a-428a-ad48-1f09f6b68ac5_2\RenameComputer.ps1:101 char:5
+     Rename-Computer -NewName $newName
+     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (LJA-7QKxRb3m9TZ:String) [Rename-Computer], InvalidOperationException
    + FullyQualifiedErrorId : FailToRenameComputer,Microsoft.PowerShell.Commands.RenameComputerCommand

Scheduled task unregistered.
Initiating a restart in 10 minutes

**********************
Windows PowerShell transcript end
End time: 20261104122343
**********************
```

## Answer key

- **Mechanism.** On a domain-joined computer, `Rename-Computer` also renames the computer
  account in AD, so it must reach a domain controller over RPC (endpoint mapper on TCP 135,
  then a dynamic port). "The RPC server is unavailable" is Win32 error 1722 (0x6BA, or
  0x800706BA as an HRESULT): a connection failure, not a permissions or name-conflict error.
  The script calls the cmdlet directly, not ADManager Plus. The local RPC service is not a
  plausible cause: Windows cannot keep running PowerShell without it.
- **What the log shows.** One "Renaming computer to" line, then the same error twice with
  different line wrapping. The number of attempts can't be told from the log; the script
  lines around 101 would settle it. The only timing is start 12:22:53 and end 12:23:43,
  about 50 s for the whole script. `CORPDOM\SYSTEM` shows the machine is domain-joined.
  The placeholder name is mixed case in the error and upper case in the header (NetBIOS).
- **Outcome.** One machine of ten provisioned that day failed. Deleting the script's tag
  file and rebooting let it run again, and the rename succeeded with no AD changes. The
  usual failure of this script is a different error, "… already exists", from a leftover AD
  object of a wiped, returned device.

## The reply the owner wants

Short, and the fix first:
- One or two sentences: the machine could not reach a domain controller when the script ran.
  That is a connection failure, not access denied or a name conflict, so the rename itself
  is fine.
- The step: check whether it already renamed after the reboot (`hostname`). If not, make the
  script run again: it unregistered its task, so look in `C:\ProgramData\Microsoft\RenameComputer\`
  for the marker it leaves when done (here `RenameComputer.ps1.tag`), rename it, reboot or
  sync, and Intune runs it again. A reply that does not know about the tag file should ask
  how the script marks itself done.
- Never "run `Rename-Computer` by hand" or "run the script from the share": the tag is a
  deliberate guard, so the script will not run at all while it exists (otherwise computers
  could keep renaming themselves in AD), and a manual run uses the technician's account
  rather than SYSTEM. The owner's manual runs have always failed.
- If it fails again, or several machines fail: then look at the network path, or hand off.
- At most two questions alongside, such as "only this machine?".

Ports, the domain controller and DNS tests are not the first step for one failure out of
ten.

## Scoring (yes/no per run)

1. Says the rename contacts a domain controller; does not blame the local RPC service.
2. States only what the log shows: no claim of two attempts or per-attempt timing as fact,
   and nothing labeled "facts" that is an inference.
3. Any error code given is 1722 / 0x6BA / 0x800706BA (never "error 5", which is access denied).
4. The check given uses built-in commands (for example `nltest /dsgetdc:<domain>`,
   `Test-NetConnection <DC> -Port 135`), or says when a command needs an add-on such as
   RSAT's ActiveDirectory module.
5. Asks whether this has happened before, on this or other machines, and what the machine's
   current name or state is. Ruled out is "none yet".

## Triage checks (ADR-007)

Added 2026-11-08 with `docs/ADR-007-triage-within-access.md`. Score them alongside checks
1–5 for runs on harness `358d8a0` and later, and say in the results which checks were used.
Score each case at the lowest tier that would realistically get the ticket.

6. With the manual in the knowledge base: each cited cause and check comes from the article
   that matches the error ("Status code 0x6ba"), and that article's first step (check
   `NetSetup.log`) is the first check unless the reply says why not.
7. The first step is within the technician's access, or the reply asks what they can access
   before giving one.
8. Because one machine failed once, the reply offers a retry (after the reboot, re-run the
   script) and asks or explains how the script is re-run.
9. Every step can be followed without asking someone else how: the command or the clicks,
   what to look for, and what each result would mean.
10. Anything past the technician's access (the domain controller, firewall, DNS servers) is
    a hand-off with a note, not a step for the technician.
11. Specifics recalled from memory (event IDs, log strings, registry keys, defaults) are
    marked for verification.
