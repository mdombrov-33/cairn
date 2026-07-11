# Concrete query adapters without repository protocols

Application workflows use the concrete modules in `db/queries/` as their persistence adapters rather
than defining generic repository protocols. Postgres is the only real persistence implementation;
adding a second interface would widen every workflow and test without providing variation, while the
query modules and application workflows already keep SQLAlchemy and database operations out of domain
rules.
