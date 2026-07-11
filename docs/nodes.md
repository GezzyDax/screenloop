# Node Mode (remote sites)

Node mode lets one Screenloop controller manage TVs in remote LANs (branch offices, other VLANs) without any inbound ports at the remote site.

```
Site A (branch)                        Central server
┌─────────────────────────┐            ┌─────────────────────────┐
│ TVs ──► node:8099/stream│            │ browsers ──► ui:8098    │
│        screenloop-node  │══ wss ════►│ screenloop (controller) │
│        (cache + SOAP)   │  outbound  │ DB, users, transcoding  │
└─────────────────────────┘            └─────────────────────────┘
```

- The **controller** keeps the database, users, uploads, and all ffmpeg transcoding, and manages TVs in its own LAN exactly as before.
- A **node** discovers and controls TVs in its LAN over DLNA/SOAP, pre-caches transcoded media from the controller, serves `/stream` to its TVs locally, and keeps playlists looping even when the controller is unreachable.
- The node connects **outbound** over the controller's normal HTTP(S) port (websocket). Behind a TLS proxy this is `wss://` automatically.

## Setting up a node

1. In the panel (admin): **Nodes → Create node**. Copy the one-time enrollment token (shown once, valid 24h).
2. On the remote host:

   ```bash
   sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --node http://<controller>:8099'
   ```

   The installer asks for the enrollment token and starts the `screenloop-node` container (host network, data in the `screenloop-node-data` volume).
3. The node appears online on the Nodes screen. Remove `SCREENLOOP_NODE_ENROLL_TOKEN` from the node's `.env` afterwards — it is single-use.
4. Assign TVs to the node: **TVs → Add TV → Node**, or edit an existing TV. Node TVs are polled by the node; commands from the panel are routed to it automatically.

## Node environment

- `SCREENLOOP_NODE_CONTROLLER_URL` — controller base URL (required).
- `SCREENLOOP_NODE_ENROLL_TOKEN` — one-time token for the first start.
- `SCREENLOOP_NODE_HTTP_PORT` — local stream port, default 8099 (same firewall rules as the controller).
- `SCREENLOOP_NODE_CACHE_BYTES` — media cache limit, default 10 GiB (LRU eviction).
- `SCREENLOOP_NODE_ADVERTISE_HOST` — IP advertised to TVs when auto-detection picks the wrong interface.

## Security model

- Enrollment tokens are single-use with a 24h TTL; permanent node tokens are stored hashed, like user sessions.
- Deleting a node revokes its token immediately: the websocket drops and media downloads stop; its TVs go offline in the panel.
- Node stream URLs are signed with the node's own token and bound to the TV address; the controller's `SCREENLOOP_SECRET_KEY` never leaves the controller.

## Offline behaviour

If the controller is unreachable, the node keeps looping the last known playlists from its local cache and reconnects with backoff. Status and command results catch up after reconnect. Media uploaded while the node is offline syncs on the next cache pass (every 30s once connected).
