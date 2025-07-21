# IPC Router

Core routing service for the AegisIPC framework.

## Overview

The IPC Router is the central component that manages message routing, service discovery, and communication patterns in the AegisIPC ecosystem.

## Architecture

Follows hexagonal architecture with clear separation of concerns:

- `api/` - External interfaces (REST, gRPC)
- `application/` - Use cases and orchestration
- `domain/` - Core business logic
- `infrastructure/` - Technical implementations (NATS, databases)
