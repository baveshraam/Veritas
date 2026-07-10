"""Synthetic data generator — Faker-free, prior-driven.

Builds an internally consistent officer/person/FIR/criminal-record dataset from
the priors and reference tables in data/seed/, then (in load/) writes it to
Postgres, syncs Neo4j, and embeds narratives. Rerunning is how the whole
dataset refreshes; there is no streaming ingestion.
"""
