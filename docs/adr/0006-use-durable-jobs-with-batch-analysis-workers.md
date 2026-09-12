# Use durable jobs with batch analysis workers

Echora stores jobs in PostgreSQL and executes them outside the API through two worker types. Analysis workers run the complete pipeline for a batch, loading each required model once per stage on CPU or GPU. Scheduled workers execute curation refreshes, including manual requests.

We chose batch workers over separate model queues to keep deployment and pipeline dependencies simpler. Song artifacts remain independently committed so retries can skip compatible completed work. Smaller batches improve fairness but repeat model loading more often, so batch size is configurable.

The same job lifecycle handles ownership, active-job discovery, claims, cancellation, and retries. Browser storage is not authoritative. Curation publication preserves its selected order before contacting Navidrome because a remote playlist update cannot commit atomically with PostgreSQL.
