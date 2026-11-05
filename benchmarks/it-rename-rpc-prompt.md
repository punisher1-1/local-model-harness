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
