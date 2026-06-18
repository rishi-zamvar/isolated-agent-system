"""Challenge-thread lifecycle (spec §8.6, §11 deadlock).

A challenge opens a thread between two agents. It is bounded to three rounds;
an unresolved third round auto-escalates to ORCH with both positions, which
guarantees the system cannot livelock on a disagreement. Once an objection is
resolved with evidence, re-raising the same locus without new information is
invalid and is dropped.
"""

MAX_ROUNDS = 3


class Thread:
    def __init__(self, correlation_id: str, producer: str, consumer: str):
        self.correlation_id = correlation_id
        self.producer = producer
        self.consumer = consumer
        self.rounds = 0
        self.resolved_loci: set[str] = set()

    def record_round(self) -> int:
        """A DEFEND/REVISE + re-review pair is one round."""
        self.rounds += 1
        return self.rounds

    def should_escalate(self, resolved: bool) -> bool:
        """Escalate to ORCH when an unresolved thread hits the round bound."""
        return (not resolved) and self.rounds >= MAX_ROUNDS

    def resolve(self, locus: str) -> None:
        self.resolved_loci.add(locus)

    def is_stale_reraise(self, locus: str, has_new_info: bool) -> bool:
        """A resolved locus re-raised without new information is invalid (§8.6)."""
        return locus in self.resolved_loci and not has_new_info
