"""Union-find over unit ids with cannot-link constraints (human `separate` always wins).

INIT-032/SPEC-010
"""

from __future__ import annotations

from collections.abc import Iterable


class ConstrainedUnionFind:
    def __init__(self, items: Iterable[int], cannot_link: Iterable[tuple[int, int]] = ()) -> None:
        self.parent: dict[int, int] = {}
        self.members: dict[int, set[int]] = {}
        self.blocked: dict[int, set[int]] = {}
        for i in items:
            self.parent[i] = i
            self.members[i] = {i}
            self.blocked[i] = set()
        for a, b in cannot_link:
            if a in self.parent and b in self.parent and a != b:
                self.blocked[self.find(a)].add(b)
                self.blocked[self.find(b)].add(a)

    def __contains__(self, item: int) -> bool:
        return item in self.parent

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def size(self, x: int) -> int:
        return len(self.members[self.find(x)])

    def can_union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        small, large = (ra, rb) if len(self.members[ra]) <= len(self.members[rb]) else (rb, ra)
        return not (self.blocked[large] & self.members[small]) and not (
            self.blocked[small] & self.members[large]
        )

    def union(self, a: int, b: int, *, max_size: int | None = None) -> bool:
        """Join a and b. False when blocked by a cannot-link or the size cap (no change)."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        if not self.can_union(ra, rb):
            return False
        if max_size is not None and len(self.members[ra]) + len(self.members[rb]) > max_size:
            return False
        if len(self.members[ra]) < len(self.members[rb]):
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.members[ra] |= self.members.pop(rb)
        self.blocked[ra] |= self.blocked.pop(rb)
        return True

    def components(self) -> dict[int, list[int]]:
        """root-independent: keyed by the smallest member id, members sorted."""
        out: dict[int, list[int]] = {}
        for root, mem in self.members.items():
            ordered = sorted(mem)
            out[ordered[0]] = ordered
        return out

    def comp_of(self) -> dict[int, int]:
        """item -> smallest member id of its component (a stable component id)."""
        result: dict[int, int] = {}
        for ordered in self.components().values():
            cid = ordered[0]
            for m in ordered:
                result[m] = cid
        return result
