# Demo backup policy
Synthetic training data for fictional Cedar Works; not a real operational policy.

Cedar Works takes an encrypted nightly backup of its ticketing database at 02:00 UTC.
The retention period is 30 days. The recovery point objective (RPO) is 24 hours.
The recovery time objective (RTO) is 4 hours. These objectives are targets, not proof
of a successful recovery. The latest exercise results are in recovery-exercise.
A backup copy alone does not validate credentials, dependencies, DNS changes, or the
ability to restore the application. Do not infer actual readiness from a successful
backup job. Policy owner: the fictional Infrastructure Team.
