"""Run the simulated network over HTTP (optional): `python -m network.serve` then open
http://127.0.0.1:8000/docs. The broker is served at /, and each node at /nodes/<id> (nodes
require broker-issued tokens, so direct calls return 401 by design).

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import uvicorn

from labcore.config import RAW_DIR

from .broker import Broker, create_broker_app


def app():
    broker = Broker(RAW_DIR)
    root = create_broker_app(broker)
    for node_id, cli in broker.nodes.items():
        root.mount(f"/nodes/{node_id}", cli.app)
    return root


if __name__ == "__main__":
    uvicorn.run(app(), host="127.0.0.1", port=8000)
