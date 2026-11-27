# Order Orchestration Rule Engine

This project contains an offline, deterministic, rule-based order orchestration engine for aftermarket dealer orders.

## Current Scope

The engine is designed to support:

- VOR orders
- Replenishment orders
- Push orders
- Parent RDC stock checks
- Parent-bound GIT checks
- Cluster RDC checks
- PAN-India RDC checks
- VEPDC checks
- Safety stock protection
- Single-source allocation
- Candidate evaluation and reason codes
- Historical simulation

## Current Development Stage

Stage 2: Repository structure, configuration files, domain objects, exceptions, and basic tests.

## Setup

```bash
pip install -e .
pip install pytest pyyaml pandas