"""Exact bijection between integers and the spanning trees of a maze graph.

A perfect maze is a spanning tree of the graph that joins neighbouring cells,
so a shape with ``count`` spanning trees has exactly that many mazes and one
maze can carry log2(count) bits.  The classes here map each integer in
``range(count)`` to a distinct tree (``unrank``) and back (``rank``), which is
what makes that capacity usable.

``LayeredTrees`` does the work for any graph whose nodes come in layers with
edges only inside a layer or between neighbouring layers: the rows of a grid,
or the rings of a circle.  ``GridTrees`` is the grid, whole or with cells
blocked out.

Edges are visited in a fixed order, layer by layer.  At each edge we need to
know how many of the trees still possible contain it; those with a smaller
index keep the edge, the rest drop it.  Kept edges are contracted, so
everything before the current layer collapses into classes of connected nodes.

The counts come from Kirchhoff's theorem.  With ``tau`` the number of spanning
trees of the current (contracted) graph and G the inverse of its Laplacian
with one class grounded, the trees containing edge (u, v) number

    tau * (G[u][u] + G[v][v] - 2 G[u][v])

All arithmetic is on the integer matrix ``A = tau * G`` restricted to the
classes that still touch undecided edges, so nothing is ever approximated:

    keep (contract):  A <- (inside * A - w w^T) / tau,          tau <- inside
    drop (delete):    A <- ((tau - inside) * A + w w^T) / tau,  tau <- tau - inside

where ``w = A (e_u - e_v)`` and ``inside = w[u] - w[v]``.  Every division is
exact.  The layers after the current one are never touched by a decision, so
their electrical response is the same for every tree and is precomputed.

Cost is about the sum of ``size**3`` over the layers, in big-integer
operations on numbers of roughly 1.6 bits per node.
"""

from functools import cached_property
from math import log2
from operator import mul

GROUND = -1


def _dot(xs, ys):
    return sum(map(mul, xs, ys))


def _solve(M, columns, scale=1):
    """Fraction-free (Bareiss) solve of ``M x = b`` for each column ``b``,
    for a symmetric positive definite integer matrix.

    Returns ``(d, [d * x, ...])`` with ``d = det M / scale**(n - 1)``.  A
    ``scale`` other than 1 is for when M and the columns are ``scale`` times a
    matrix whose minors all have denominator ``scale`` (a Schur complement of
    a Laplacian).  Every k x k minor of M then carries ``scale**(k - 1)``, and
    dividing the first step by ``scale`` keeps that factor out of the rest.
    """
    n = len(M)
    a = [row[:] for row in M]
    columns = [column[:] for column in columns]
    prev = scale
    for k in range(n - 1):
        ak = a[k]
        akk = ak[k]
        for i in range(k + 1, n):
            ai, aki = a[i], ak[i]
            for j in range(i, n):
                ai[j] = (ai[j] * akk - aki * ak[j]) // prev
        for c in columns:
            ck = c[k]
            for i in range(k + 1, n):
                if ck or c[i]:
                    c[i] = (c[i] * akk - ak[i] * ck) // prev
        prev = akk
    det = a[-1][-1] if n else 1
    solutions = []
    for c in columns:
        x = [0] * n
        for i in reversed(range(n)):
            x[i] = (det * c[i] - _dot(a[i][i + 1:], x[i + 1:])) // a[i][i]
        solutions.append(x)
    return det, solutions


class _Frontier:
    """``tau`` and ``A = tau * G`` for the graph left after the decisions so far."""

    def __init__(self):
        self.A = []
        self.live = []
        self.tau = 1

    def resolve(self, u, v, choose):
        """Decide the edge between classes ``u`` and ``v``.

        ``choose(inside, total)`` is told how many of the ``total`` remaining
        trees contain the edge and returns whether to keep it.  Returns
        ``(gone, into)`` if the edge was kept and class ``gone`` merged into
        ``into``, else None.
        """
        A, live, tau = self.A, self.live, self.tau
        if u == v:
            # Already connected: the edge would close a loop.
            choose(0, tau)
            return None
        if u == GROUND:
            u, v = v, u
        if v == GROUND:
            w = A[u][:]
            inside = w[u]
        else:
            w = [x - y for x, y in zip(A[u], A[v])]
            inside = w[u] - w[v]
        keep = choose(inside, tau)
        if keep:
            live.remove(u)
            scale, signed = inside, [-x for x in w]
        else:
            scale, signed = tau - inside, w
        for a, i in enumerate(live):
            Ai, wi = A[i], signed[i]
            for j in live[a:]:
                Ai[j] = A[j][i] = (scale * Ai[j] + wi * w[j]) // tau
        self.tau = scale
        return (u, v) if keep else None


class LayeredTrees:
    """The spanning trees of a layered graph, indexed 0..count-1.

    Layer s has ``sizes[s]`` nodes.  ``inner[s]`` lists the edges ``(i, j)``
    between nodes i and j of layer s, and ``links[s]`` the edges ``(i, j)``
    from node i of layer s - 1 to node j of layer s (``links[0]`` is empty).
    The graph must be connected.

    A tree is a pair ``(linked, lateral)``: for each layer, which of its
    ``links`` and which of its ``inner`` edges the tree has, as booleans in
    the same order.
    """

    def __init__(self, sizes, inner, links):
        self.sizes, self.inner, self.links = sizes, inner, links
        self.cells = sum(sizes)
        if not self.cells or not self._connected():
            raise ValueError("the cells must form one connected area")
        self._below = None

    def _connected(self):
        near = {}
        for s in range(len(self.sizes)):
            for i, j in self.inner[s]:
                near.setdefault((s, i), []).append((s, j))
                near.setdefault((s, j), []).append((s, i))
            for i, j in self.links[s]:
                near.setdefault((s - 1, i), []).append((s, j))
                near.setdefault((s, j), []).append((s - 1, i))
        if not self.sizes[0]:
            return False
        seen, stack = {(0, 0)}, [(0, 0)]
        while stack:
            for node in near.get(stack.pop(), ()):
                if node not in seen:
                    seen.add(node)
                    stack.append(node)
        return len(seen) == self.cells

    @cached_property
    def count(self):
        """The number of spanning trees."""
        return self._layers_below(None)[0][0]

    # -- the layers after the frontier ---------------------------------------
    #
    # For layer s, take the layers from s on and tie each node of layer s to a
    # ground node once per link it has to layer s - 1.  (Layer 0 has none; it
    # is tied at ``_ties``.)  ``below[s]`` describes that graph: its number of
    # spanning trees t, and t times its Green's function on layer s.

    _ties = (0,)

    def _layers_below(self, progress):
        if self._below is None:
            self._below = self._build_below(progress)
        return self._below

    def _build_below(self, progress):
        """Work backwards one layer at a time.  Layer s sees the layers after
        it through their Green's function, which gives a matrix to invert."""
        sizes, last = self.sizes, len(self.sizes) - 1
        below = [None] * len(sizes)
        t_next, N_next = 1, []
        for s in range(last, -1, -1):
            size = sizes[s]
            # W = t_next * (ties + Laplacian of the layer + links on) - N_next
            W = [[0] * size for _ in range(size)]
            for _, j in self.links[s] if s else [(None, 0)]:
                W[j][j] += t_next
            for i, j in self.inner[s]:
                W[i][i] += t_next
                W[j][j] += t_next
                W[i][j] -= t_next
                W[j][i] -= t_next
            on = self.links[s + 1] if s < last else []
            for i, a in on:
                W[i][i] += t_next
                row, Na = W[i], N_next[a]
                for i2, b in on:
                    row[i2] -= Na[b]
            unit = [[t_next * (i == j) for i in range(size)] for j in range(size)]
            t_next, N_next = _solve(W, unit, t_next)
            below[s] = (t_next, N_next)
            if progress:
                progress(last - s + 1, 2 * (last + 1))
        return below

    def _matrix(self, data):
        return data

    # How much of the work the sweep is, out of 10; the rest is the layers below.
    _sweep_share = 5

    # -- the sweep -----------------------------------------------------------

    def _walk(self, decide, progress):
        """Visit every edge in canonical order: for each layer s, its links
        to layer s - 1, then its inner edges.

        ``decide(linked, s, k, inside, total)`` returns whether to keep edge
        ``links[s][k]`` (``linked`` true) or ``inner[s][k]``.
        """
        layers = len(self.sizes)
        below = self._layers_below(progress)
        fr = _Frontier()
        top = []  # the class of each node of the layer before
        for s in range(layers):
            size = self.sizes[s]
            t, data = below[s]
            N = self._matrix(data)
            if s == 0:
                fr.tau = t

            # Bring layer s into the frontier next to the k classes before it.
            live, tau = fr.live, fr.tau
            k = len(live)
            slot = {c: i for i, c in enumerate(live)}
            top = [c if c == GROUND else slot[c] for c in top]
            TT = [[fr.A[a][b] for b in live] for a in live]
            P = [[0] * size for _ in range(k)]
            for u, i in self.links[s]:
                c = top[u]
                if c != GROUND:
                    P[c] = [p + x for p, x in zip(P[c], N[i])]
            Pcols = list(zip(*P)) if k else [()] * size
            Tb = [[_dot(TT[c], col) // t for col in Pcols] for c in range(k)]
            Tbcols = list(zip(*Tb)) if k else [()] * size
            A = [TT[c] + Tb[c] for c in range(k)]
            A += [list(Tbcols[i]) + [0] * size for i in range(size)]
            for i in range(size):
                for j in range(i, size):
                    A[k + i][k + j] = A[k + j][k + i] = (
                        tau * N[i][j] + _dot(Pcols[i], Tbcols[j])) // t
            fr.A, fr.live = A, list(range(k + size))
            cur = [k + i for i in range(size)]

            def settle(u, v, choose):
                nonlocal cur, top
                merged = fr.resolve(u, v, choose)
                if merged:
                    gone, into = merged
                    cur = [into if c == gone else c for c in cur]
                    top = [into if c == gone else c for c in top]

            if s == 0:
                # Nothing is before layer 0.  Its ties to the ground are
                # forced: the first is kept, which grounds that node, and any
                # others are dropped.
                for i in self._ties:
                    settle(cur[i], GROUND, lambda inside, total, i=i: i == self._ties[0])
                assert fr.tau == self.count
            for n, (u, i) in enumerate(self.links[s]):
                settle(cur[i], top[u],
                       lambda inside, total, n=n: decide(True, s, n, inside, total))
            for n, (i, j) in enumerate(self.inner[s]):
                settle(cur[j], cur[i],
                       lambda inside, total, n=n: decide(False, s, n, inside, total))
            assert set(fr.live) <= set(cur)
            top = cur
            if progress:
                share = self._sweep_share
                progress((10 - share) * layers + share * (s + 1), 10 * layers)
        assert fr.tau == 1 and not fr.live

    # -- public API ----------------------------------------------------------

    def unrank(self, index, progress=None):
        """The tree with the given index, as ``(linked, lateral)``."""
        if not 0 <= index < self.count:
            raise ValueError(f"index must be in range({self.count})")
        linked = [[False] * len(edges) for edges in self.links]
        lateral = [[False] * len(edges) for edges in self.inner]
        left = index

        def decide(is_link, s, k, inside, total):
            nonlocal left
            if left < inside:
                (linked if is_link else lateral)[s][k] = True
                return True
            left -= inside
            return False

        self._walk(decide, progress)
        return linked, lateral

    def rank(self, linked, lateral, progress=None):
        """The index of a tree; raises ValueError if it is not a spanning tree."""
        if ([len(row) for row in linked] != [len(edges) for edges in self.links]
                or [len(row) for row in lateral] != [len(edges) for edges in self.inner]):
            raise ValueError("not a maze of this shape")
        index = 0

        def decide(is_link, s, k, inside, total):
            nonlocal index
            if (linked if is_link else lateral)[s][k]:
                if not inside:
                    raise ValueError("not a perfect maze: it contains a loop")
                return True
            if inside == total:
                raise ValueError("not a perfect maze: some cells are cut off")
            index += inside
            return False

        self._walk(decide, progress)
        return index

    def estimate_bits(self):
        """log2 of ``count``, in floating point.

        Quick enough to call while a shape is being edited; the exact count
        takes as long as encoding does.
        """
        start = [0]
        for size in self.sizes:
            start.append(start[-1] + size)
        # Gaussian elimination on the Laplacian with the last node grounded,
        # kept sparse: in sweep order a row only reaches one layer ahead.
        n = self.cells - 1
        diag = [0.0] * (n + 1)
        upper = [{} for _ in range(n + 1)]
        for s in range(len(self.sizes)):
            edges = [(start[s] + i, start[s] + j) for i, j in self.inner[s]]
            edges += [(start[s - 1] + i, start[s] + j) for i, j in self.links[s]]
            for a, b in edges:
                a, b = min(a, b), max(a, b)
                diag[a] += 1
                diag[b] += 1
                upper[a][b] = upper[a].get(b, 0.0) - 1.0
        bits = 0.0
        for i in range(n):
            pivot = diag[i]
            bits += log2(pivot)
            row = sorted((j, v) for j, v in upper[i].items() if j < n)
            for a, (j, v) in enumerate(row):
                factor = v / pivot
                diag[j] -= factor * v
                target = upper[j]
                for k, w in row[a + 1:]:
                    target[k] = target.get(k, 0.0) - factor * w
        return bits


class GridTrees(LayeredTrees):
    """The spanning trees of a grid graph, indexed 0..count-1.

    The graph has the cells of a rows x cols grid that are not in ``blocked``
    (a collection of ``(row, col)``), which must form one connected area.  A
    tree is given as two boolean grids: ``down[r][c]`` joins cells (r, c) and
    (r + 1, c), ``right[r][c]`` joins (r, c) and (r, c + 1).
    """

    def __init__(self, rows, cols, blocked=()):
        if rows < 1 or cols < 1:
            raise ValueError("a grid needs at least one row and one column")
        self.rows, self.cols = rows, cols
        self.blocked = frozenset(map(tuple, blocked))
        if any(not (0 <= r < rows and 0 <= c < cols) for r, c in self.blocked):
            raise ValueError("a blocked cell lies outside the grid")
        # Sweep along the long side so the frontier is the short one.
        self._flip = cols > rows
        self._n, self._m = max(rows, cols), min(rows, cols)
        # The columns present in each row of the swept grid, without the
        # empty rows at either end.
        lines = [[j for j in range(self._m)
                  if ((j, s) if self._flip else (s, j)) not in self.blocked]
                 for s in range(self._n)]
        occupied = [s for s, line in enumerate(lines) if line]
        if not occupied:
            raise ValueError("every cell is blocked")
        self._first = occupied[0]
        lines = lines[self._first:occupied[-1] + 1]
        # Where each edge sits in the swept grid: (row, column of its far end).
        self._link_at, self._inner_at = [], []
        inner, links, above = [], [], {}
        for s, line in enumerate(lines, self._first):
            here = {j: i for i, j in enumerate(line)}
            links.append([(above[j], i) for i, j in enumerate(line) if j in above])
            self._link_at.append([(s, j) for j in line if j in above])
            inner.append([(here[j - 1], i) for i, j in enumerate(line) if j - 1 in here])
            self._inner_at.append([(s, j) for j in line if j - 1 in here])
            above = here
        self._uniform = not self.blocked
        super().__init__([len(line) for line in lines], inner, links)

    @cached_property
    def count(self):
        if not self._uniform:
            return self._layers_below(None)[0][0]
        # U[0] - U[1] is prod_i (L + mu_i) over the eigenvalues mu_i of the
        # long-side path Laplacian; any cofactor of it is the tree count.
        U = self._transfer()
        minor = [[x - y for x, y in zip(ra[1:], rb[1:])]
                 for ra, rb in zip(U[0][1:], U[1][1:])]
        return _solve(minor, [])[0]

    # -- a full grid: every row is the same path -----------------------------
    #
    # Each matrix below is then a function of the path Laplacian L, which
    # gives a far cheaper way to build them, and only their first rows need
    # keeping.  Row 0 is tied to the ground at every cell rather than one.

    @property
    def _ties(self):
        return range(self._m) if self._uniform else (0,)

    @property
    def _sweep_share(self):
        return 9 if self._uniform else 5

    def _lap_mul(self, M, c):
        """(c I + L) M, where L is the Laplacian of a path on the short side."""
        m = self._m
        deg = [0] if m == 1 else [1] + [2] * (m - 2) + [1]
        out = []
        for i in range(m):
            row = [(c + deg[i]) * x for x in M[i]]
            if i:
                row = [x - y for x, y in zip(row, M[i - 1])]
            if i + 1 < m:
                row = [x - y for x, y in zip(row, M[i + 1])]
            out.append(row)
        return out

    def _transfer(self):
        """U[s] = q_s(L) with q_n = 1, q_{n-1} = 1 + x and
        q_s = (2 + x) q_{s+1} - q_{s+2}.

        The graph for row s has det U[s] spanning trees and its Green's
        function on row s is U[s+1] U[s]^-1.
        """
        n, m = self._n, self._m
        U = [None] * (n + 1)
        U[n] = [[int(i == j) for j in range(m)] for i in range(m)]
        U[n - 1] = self._lap_mul(U[n], 1)
        for s in range(n - 2, -1, -1):
            U[s] = [[x - y for x, y in zip(ra, rb)]
                    for ra, rb in zip(self._lap_mul(U[s + 1], 2), U[s + 2])]
        return U

    def _build_below(self, progress):
        if not self._uniform:
            return super()._build_below(progress)
        n, m = self._n, self._m
        U = self._transfer()
        e0 = [1] + [0] * (m - 1)
        below = []
        for s in range(n):
            t, (y,) = _solve(U[s], [e0])
            below.append((t, [_dot(y, col) for col in zip(*U[s + 1])]))
            if progress:
                progress(s + 1, 10 * n)
        return below

    def _matrix(self, data):
        if not self._uniform:
            return data
        # Rebuild F = f(L) from its first row, using F L = L F.
        m = self._m
        deg = [0] if m == 1 else [1] + [2] * (m - 2) + [1]
        F = [data]
        prev = [0] * m
        for i in range(m - 1):
            row = F[i]
            F.append([(row[j - 1] if j else 0) + (row[j + 1] if j + 1 < m else 0)
                      - prev[j] + (deg[i] - deg[j]) * row[j] for j in range(m)])
            prev = row
        return F

    # -- trees as passages between cells -------------------------------------

    def _passages(self):
        """Every edge as (is a link, layer, number, passage grid name, r, c)."""
        for is_link, places in ((True, self._link_at), (False, self._inner_at)):
            for layer, row in enumerate(places):
                for k, (s, j) in enumerate(row):
                    if is_link:
                        where = ("right", j, s - 1) if self._flip else ("down", s - 1, j)
                    else:
                        where = ("down", j - 1, s) if self._flip else ("right", s, j - 1)
                    yield (is_link, layer, k) + where

    def unrank(self, index, progress=None):
        """The tree with the given index, as ``(down, right)``."""
        linked, lateral = super().unrank(index, progress)
        grids = {"down": [[False] * self.cols for _ in range(self.rows - 1)],
                 "right": [[False] * (self.cols - 1) for _ in range(self.rows)]}
        for is_link, layer, k, grid, r, c in self._passages():
            grids[grid][r][c] = (linked if is_link else lateral)[layer][k]
        return grids["down"], grids["right"]

    def rank(self, down, right, progress=None):
        """The index of a tree; raises ValueError if it is not a spanning tree."""
        if (len(down) != self.rows - 1 or len(right) != self.rows
                or any(len(row) != self.cols for row in down)
                or any(len(row) != self.cols - 1 for row in right)):
            raise ValueError(f"not a {self.rows}x{self.cols} grid")
        # The sweep only looks at edges between cells of the graph.
        for r, c in self.blocked:
            if (r and down[r - 1][c] or r + 1 < self.rows and down[r][c]
                    or c and right[r][c - 1] or c + 1 < self.cols and right[r][c]):
                raise ValueError("not a perfect maze: a passage leads into a blocked cell")
        grids = {"down": down, "right": right}
        linked = [[False] * len(edges) for edges in self.links]
        lateral = [[False] * len(edges) for edges in self.inner]
        for is_link, layer, k, grid, r, c in self._passages():
            (linked if is_link else lateral)[layer][k] = bool(grids[grid][r][c])
        return super().rank(linked, lateral, progress)


def estimate_bits(rows, cols, blocked=()):
    """log2 of ``GridTrees(rows, cols, blocked).count``, in floating point."""
    return GridTrees(rows, cols, blocked).estimate_bits()
