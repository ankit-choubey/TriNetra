"""
Agent 4: GST Reconciliation Agent
Approach: Graph Theory & Deterministic Math
Tools: networkx (Directed Graphs)

Trigger: parsing_completed
Reads: documents (GST files)
Writes: gst_analysis
Logic: Compare GSTR-3B ITC claimed vs GSTR-2B auto-populated.
       Build networkx directed graph for circular trading detection.
Errors: GST_PARSE_FAIL → flag gst_analysis.reconciliation_status=ERROR.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.agent_base import AgentBase

import networkx as nx


def compute_itc_discrepancy(gst_2b_data: dict, gst_3b_data: dict) -> dict:
    """
    Compare GSTR-2B (auto-populated ITC) vs GSTR-3B (claimed ITC).
    Returns discrepancy percentage and mismatch flag.
    """
    itc_2b = gst_2b_data.get("total_itc", 0.0)
    itc_3b = gst_3b_data.get("itc_claimed", 0.0)

    if itc_2b > 0:
        discrepancy_pct = abs(itc_3b - itc_2b) / itc_2b
    else:
        discrepancy_pct = 1.0 if itc_3b > 0 else 0.0

    return {
        "itc_2b": itc_2b,
        "itc_3b": itc_3b,
        "discrepancy_pct": round(discrepancy_pct * 100, 2),
        "itc_mismatch_flag": discrepancy_pct > 0.10,  # >10% = flag
    }


def detect_circular_trading(transactions: list, max_cycle_length: int = 4) -> dict:
    """
    Build a directed graph from buyer/seller transactions
    and detect circular trading using networkx cycle detection.

    A circular trade is: A -> B -> C -> A (inflating revenue with no real business).

    Args:
        transactions: list of dicts with 'seller_gstin' and 'buyer_gstin'.
        max_cycle_length: maximum cycle length to detect (default 4).

    Returns:
        dict with cycle info and circular_trade_index.
    """
    G = nx.DiGraph()

    for txn in transactions:
        seller = txn.get("seller_gstin", "")
        buyer = txn.get("buyer_gstin", "")
        amount = txn.get("amount", 0.0)
        if seller and buyer and seller != buyer:
            if G.has_edge(seller, buyer):
                G[seller][buyer]["weight"] += amount
                G[seller][buyer]["count"] += 1
            else:
                G.add_edge(seller, buyer, weight=amount, count=1)

    suspicious_cycles = []

    # Only check for cycles if graph has edges
    if G.number_of_edges() > 0:
        try:
            for cycle in nx.simple_cycles(G):
                if len(cycle) <= max_cycle_length:
                    cycle_amount = sum(
                        G[cycle[i]][cycle[(i + 1) % len(cycle)]].get("weight", 0)
                        for i in range(len(cycle))
                    )
                    suspicious_cycles.append({
                        "parties": cycle,
                        "cycle_length": len(cycle),
                        "total_amount": round(cycle_amount, 2),
                    })
        except nx.NetworkXError:
            pass

    # Circular trade index: ratio of cyclic transaction volume to total volume
    total_volume = sum(
        data.get("weight", 0) for _, _, data in G.edges(data=True)
    )
    cyclic_volume = sum(c["total_amount"] for c in suspicious_cycles)
    circular_trade_index = (
        round(cyclic_volume / total_volume, 4) if total_volume > 0 else 0.0
    )

    return {
        "suspicious_cycles": suspicious_cycles,
        "circular_trade_index": circular_trade_index,
        "total_edges": G.number_of_edges(),
        "total_nodes": G.number_of_nodes(),
    }


class GSTReconciliationAgent(AgentBase):
    AGENT_NAME = "gst-reconciliation-agent"
    LISTEN_TOPICS = ["parsing_completed"]
    OUTPUT_NAMESPACE = "gst_analysis"
    OUTPUT_EVENT = "gst_completed"

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Compare GSTR-2B vs 3B for ITC discrepancy.
        Build networkx graph for circular trading detection.
        """
        documents = ucso.get("documents", {}).get("files", [])

        # Extract GST data from parsed documents
        gst_2b_data = {}
        gst_3b_data = {}
        transactions = []

        for doc in documents:
            if not doc.get("parsed"):
                continue
            extracted = doc.get("extracted_fields", {})

            if doc.get("type") == "GST_RETURN":
                # Check which GST form this is
                form_type = extracted.get("form_type", "")
                if "2B" in form_type.upper():
                    gst_2b_data = extracted
                elif "3B" in form_type.upper():
                    gst_3b_data = extracted

                # Collect transaction-level data for circular trade detection
                txns = extracted.get("transactions", [])
                transactions.extend(txns)

        # ITC Discrepancy
        itc_result = compute_itc_discrepancy(gst_2b_data, gst_3b_data)

        # Circular Trading Detection
        circular_result = detect_circular_trading(transactions)

        # Determine reconciliation status
        has_itc_issue = itc_result["itc_mismatch_flag"]
        has_circular = circular_result["circular_trade_index"] > 0.05

        if has_itc_issue and has_circular:
            status = "FLAG"
        elif has_itc_issue or has_circular:
            status = "WARNING"
        else:
            status = "OK"

        return {
            "gstr2b_vs_3b_discrepancy_pct": itc_result["discrepancy_pct"],
            "circular_trade_index": circular_result["circular_trade_index"],
            "suspicious_cycles": circular_result["suspicious_cycles"],
            "reconciliation_status": status,
            "itc_mismatch_flag": itc_result["itc_mismatch_flag"],
        }


if __name__ == "__main__":
    agent = GSTReconciliationAgent()
    agent.run()
