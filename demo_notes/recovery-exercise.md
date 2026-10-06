# Demo recovery exercise
Synthetic training data for fictional Cedar Works; no real customer information.

On 2026-08-20, the ticketing recovery exercise restored the database in 35 minutes.
Application validation and the DNS cutover took another 50 minutes, for an overall
recovery of 85 minutes. The team used the previous night's backup, whose data was
10 hours old. Thus this exercise met the policy's 4-hour RTO and 24-hour RPO.
An expired test credential caused a 15-minute delay included in the 50-minute
validation/cutover phase. The follow-up action is a pre-exercise credential check.
These results apply to this single exercise, not a guarantee for future incidents.
