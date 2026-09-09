# Regional Exit Nodes

This project is designed as a control/configuration layer. A country-specific public exit IP must come from a real egress node in that country; Railway Static Outbound IPs are outbound-only and are not inbound VPN addresses.

## Planned regions

- NL — Netherlands
- DE — Germany
- GB — United Kingdom
- US — United States

## Node contract

Each exit node should expose a private or authenticated forwarding interface to the control service and report:

- region
- public IPv4/IPv6
- health status
- latency
- last successful health check
- capacity

Do not store node credentials, private keys, or tokens in Git. Use Railway environment variables or another secret store.

## Resilience

The controller should select a healthy node, fail over when health checks fail, and avoid claiming zero downtime. No design can guarantee that a network path will never be blocked or interrupted.
