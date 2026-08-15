# Synthetic service-request review material

This material is fictional and domain-neutral. A review team receives service
requests, checks that required fields are present, selects a routing category,
and records a disposition. A queue owner is accountable for the process. A
policy approver must approve any exception before it is released. Reviewers may
not change policy or release an exception without that approval.

A synthetic four-week measurement covers 240 requests at 60 requests per week.
Median completion time was 17 minutes; 36 requests were returned for missing
fields and 14 required an exception. The desired outcome is median completion
time at or below 12 minutes while preserving approval and an auditable
disposition. Rework is material, but no monetary cost has been measured. Treat
these measurements as an observation owned by the queue analyst and dated
2026-08-01.

A synthetic tabletop exercise estimates that deterministic checks can identify
missing required fields and retrieve a routing rule. It also estimates that an
assisting author can draft a routing explanation, with a 10-minute median on
the exercise set. The path and tool order can be predefined; runtime tool
choice and replanning are not required. Completion and effects are independently
checkable from the disposition and audit entry. Treat these trial statements as
an estimate owned by the engineering lead, not as an observation.

No measurement is supplied for difficult-case accuracy, production capacity,
security exposure, integration burden, evaluation burden, maintainability, or
whether the trial design is globally optimal. Preserve those facts as unknown,
assumptions, or missing evidence. The current human review is the strongest
represented simpler option. Exception release is consequential and not
independently reversible; its blast radius is bounded to one request. Policy
does not permit autonomous exception release. An accountable owner, audit
trail, timely approver intervention, and fallback to human review are available.

