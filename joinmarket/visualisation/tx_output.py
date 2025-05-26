from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple
from typing import Protocol, MutableMapping, Iterable

class TxOutputProvider(Protocol):
    """
    A callable that receives the complete mapping of
        (txid, n) ➜ TxOutput
    and may mutate the TxOutput objects in-place.
    """
    def __call__(self,
                 outputs: MutableMapping[tuple[str, int], "TxOutput"]
                 ) -> None: ...


@dataclass(slots=True)
class TxOutput:
    """
    Canonical description of ONE transaction output.
      * spender       – (txid, vin-index) if it is spent **inside our CJ set**,
                        otherwise None.
      * role          – 'cj_out' | 'maker' | 'taker' | 'unknown'
    """
    txid:      str
    n:         int
    value:     float
    address:   str | None
    role:      str = "unknown"
    spender:   Tuple[str, int] | None = None     # filled after spend scan
    client:    str | None = None        # ← injected later
    role_whitebox: str | None = None
    tags:      Set[str]               = field(default_factory=set)
    meta:      Dict[str, Any]          = field(default_factory=dict)

    # convenient patching
    def merge(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)



# ─────────────────────────────────────────────────────────────────────────────
#  Helper: TxOutputRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TxOutputRegistry:
    """
    • builds every TxOutput from CoinJoin objects
    • annotates each output with its *spender* (if any) **inside** the CJ set
    """

    def __init__(
        self,
        *,
        cj_objs: List[Any],
        providers: Iterable[TxOutputProvider] = (),
    ) -> None:
        self.cj_objs = cj_objs
        
        # Extract transaction data from CoinJoin objects
        self.tx_map: Dict[str, dict] = {cj.txid: cj.tx for cj in cj_objs}
        self.cj_txids: Set[str] = {cj.txid for cj in cj_objs}

        self.outputs: Dict[Tuple[str, int], TxOutput] = {}
        self._build_all()

        for prov in providers:
            prov(self.outputs)

    # ─────────────────────────────────────────────────────────────────────
    #  public
    # ─────────────────────────────────────────────────────────────────────
    def __getitem__(self, key: Tuple[str, int]) -> TxOutput:
        return self.outputs[key]

    def all(self) -> Dict[Tuple[str, int], TxOutput]:
        return self.outputs

    # ─────────────────────────────────────────────────────────────────────
    #  construction
    # ─────────────────────────────────────────────────────────────────────
    def _build_all(self) -> None:
        self._from_coinjoin_objects()
        self._scan_spends()

    def _from_coinjoin_objects(self) -> None:
        """Build outputs from CoinJoin objects"""
        for cj in self.cj_objs:
            tx = cj.tx
            
            # Process all outputs to ensure we have a complete set
            for vout in tx["vout"]:
                txid, n = cj.txid, vout["n"]
                addr = vout.get("scriptPubKey", {}).get("address")
                
                # Default to unknown role
                role = "unknown"
                client = None
                
                # First create a basic output
                self.outputs[(txid, n)] = TxOutput(
                    txid=txid,
                    n=n,
                    value=vout["value"],
                    address=addr,
                    role=role,
                    client=client,
                )
                
            # Now assign roles and clients from participants
            for participant in cj.participants:
                # Process CoinJoin output
                if participant.cj_output:
                    n = participant.cj_output.n
                    self.outputs[(txid, n)].merge(
                        role="cj_out",
                        client=participant.client,
                        role_whitebox=participant.role if participant.role != "unknown" else None
                    )
                
                # Process change output if present
                if participant.change_output:
                    n = participant.change_output.n
                    self.outputs[(txid, n)].merge(
                        role=participant.role if participant.role != "unknown" else "change",
                        client=participant.client,
                        role_whitebox=participant.role if participant.role != "unknown" else None
                    )
                    # Add a tag to identify change outputs
                    self.outputs[(txid, n)].tags.add("change")

    # 3) spender annotation -------------------------------------------------
    def _scan_spends(self) -> None:
        # map   (prev_txid, prev_n)  -> (spender_txid, vin_index)
        spent: Dict[Tuple[str,int], Tuple[str,int]] = {}

        for txid, tx in self.tx_map.items():
            for idx, vin in enumerate(tx.get("vin", [])):
                prev = vin.get("txid"), vin.get("vout")
                if None not in prev and prev in self.outputs:
                    spent[prev] = (txid, idx)

        # write back to each TxOutput
        for key, spender in spent.items():
            if spender[0] in self.cj_txids:          # only cross-CJ edges matter
                self.outputs[key].spender = spender