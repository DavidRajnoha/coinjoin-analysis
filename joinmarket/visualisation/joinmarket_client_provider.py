from typing import MutableMapping, Iterable, Mapping

from joinmarket.visualisation.tx_output import TxOutput


class CJClientProvider:
    """
    One-stop provider for enriching TxOutput objects with:

    • client (always, if present in *records*)
    • tag       – configurable per instance (defaults to "client")
    • role_whitebox – only when *client_roles* is supplied

    Parameters
    ----------
    records : Iterable[dict]
        Each record must expose
            txid            : str
            output_clients  : list[str | None]
        (Same schema as CJ/whitebox exports.)

    tag : str, default "client"
        The label pushed to `TxOutput.tags` for all outputs touched
        by this provider (e.g. "client", "whitebox", "sim", …).

    client_roles : Mapping[str, str] | None, default None
        Optional truth table `{client_id: "maker"|"taker"}`.
        If *None* or empty, no `role_whitebox` field is written.

    override : bool, default False
        If True, overwrites an existing `role_whitebox`.
    """

    def __init__(
        self,
        records: Iterable[dict],
        *,
        tag: str = "client",
        client_roles: Mapping[str, str] | None = None,
        override: bool = False,
    ) -> None:
        self._tag = tag
        self._client_roles = client_roles or {}
        self._override = override

        # Build (txid, vout) ➜ client lookup
        self._map: dict[tuple[str, int], str] = {}
        for rec in records:
            txid = rec["txid"]
            for n, client in enumerate(rec.get("output_clients", [])):
                if client:                                     # skip blanks
                    self._map[(txid, n)] = client

    def __call__(
        self,
        outputs: MutableMapping[tuple[str, int], TxOutput],
    ) -> None:
        for key, client in self._map.items():
            out = outputs.get(key)
            if not out:
                continue                                      # vout outside CJ set

            # ── always attach client + tag ─────────────────
            out.client = client
            out.tags.add(self._tag)

            # ── optional white-box role ────────────────────
            if client in self._client_roles:
                if out.role_whitebox is None or self._override:
                    out.role_whitebox = self._client_roles[client]
