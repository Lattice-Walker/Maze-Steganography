# Maze-Steganography

Hide secret messages in the structure of generated mazes. This page explains
the mathematics that makes it work.

## 1. A maze is a spanning tree

Take the cells of a maze as the vertices of a graph $G$, with an edge between
every two cells that share a wall. Removing a wall keeps the corresponding
edge. A maze is *perfect* (every cell reachable, no loops) exactly when the
kept edges form a spanning tree of $G$.

So the perfect mazes of a given shape are the spanning trees of its graph. If
there are $\tau(G)$ of them, a maze can tell apart $\tau(G)$ messages and no
more: its capacity is

$$\log_2 \tau(G) \text{ bits.}$$

Reaching that capacity needs a bijection between the integers
$0, 1, \dots, \tau(G) - 1$ and the spanning trees of $G$. The rest of this page
is about building one.

## 2. Counting spanning trees

Let $L$ be the Laplacian of $G$: $L_{uu}$ is the degree of $u$, and
$L_{uv} = -1$ for each edge $uv$. Kirchhoff's matrix-tree theorem says that
$\tau(G)$ is the determinant of $L$ with one row and the same column removed.
Removing vertex $g$ this way is called *grounding* $g$; write $L_g$ for the
result.

For an $n \times m$ grid the eigenvalues of $L$ are known, which gives

$$\tau = \frac{1}{nm} \prod_{(i,j) \neq (0,0)}
\left( 4 - 2\cos\frac{\pi i}{n} - 2\cos\frac{\pi j}{m} \right),
\qquad 0 \le i < n,\ 0 \le j < m.$$

A $4 \times 4$ grid has 100352 spanning trees. As the grid grows,

$$\frac{\log_2 \tau}{nm} \longrightarrow \frac{4C}{\pi \ln 2} \approx 1.6825
\text{ bits per cell,}$$

where $C$ is Catalan's constant. Finite grids hold a little less because of
their edges: $64 \times 64$ gives 6726.8 bits, or 1.64 per cell.

## 3. From an integer to a tree

Fix an order on the edges, $e_1, e_2, \dots$ For any edge $e$,

$$\tau(G) = \tau(G / e) + \tau(G - e),$$

because the trees that contain $e$ are the spanning trees of $G$ with $e$
contracted, and those that do not are the spanning trees of $G$ with $e$
deleted. That splits the range of indices in two, and repeating it for every
edge is the bijection.

**Unranking** an index $x$ with $0 \le x < \tau(G)$: for each edge in order,

- if $x < \tau(G/e)$, keep the edge and replace $G$ by $G/e$;
- otherwise drop it, replace $x$ by $x - \tau(G/e)$ and $G$ by $G - e$.

**Ranking** a tree walks the same edges and adds $\tau(G/e)$ to a running
total every time an edge is absent. The two are inverse to each other, and
every index gives a different tree.

An edge that would close a loop joins two cells already contracted together,
so $\tau(G/e) = 0$ and it is always dropped. An edge whose removal would cut
the graph in two has $\tau(G - e) = 0$ and is always kept.

## 4. The count as an electrical measurement

Computing $\tau(G/e)$ from a fresh determinant at every edge would be far too
slow. Instead, think of $G$ as a network of unit resistors. Kirchhoff also
showed that the fraction of spanning trees containing the edge $e = uv$ is the
effective resistance between its ends:

$$\frac{\tau(G/e)}{\tau(G)} = R_{uv} = K_{uu} + K_{vv} - 2K_{uv},
\qquad K = L_g^{-1}.$$

$K$ is the Green's function of the grounded network. Its entries are
fractions, but $A = \tau K$ is a matrix of integers: by the all-minors
matrix-tree theorem, $A_{uv}$ counts the spanning forests with two trees in
which $u$ and $v$ share a tree and $g$ is in the other.

Working with $A$ keeps everything exact. With $w = A(e_u - e_v)$,

$$\tau(G/e) = w_u - w_v \quad (\text{call it } \rho),$$

and after deciding the edge the matrix for the new graph follows from a
rank-one update (the Sherman–Morrison formula):

$$\text{keep: } A \leftarrow \frac{\rho A - w w^{\mathsf T}}{\tau},\ \tau \leftarrow \rho
\qquad\qquad
\text{drop: } A \leftarrow \frac{(\tau - \rho) A + w w^{\mathsf T}}{\tau},\ \tau \leftarrow \tau - \rho.$$

Every division is exact. After a keep, the rows for $u$ and $v$ are equal and
the two vertices are merged. When the last edge is decided, $\tau = 1$ and
nothing is left.

## 5. Only the frontier matters

$A$ for the whole graph would have a row for every cell. But the graphs used
here come in *layers* (the rows of a grid, the rings of a circle), with edges
only inside a layer or between neighbouring ones. Decide the edges layer by
layer. Then:

- Everything behind the current layer has collapsed, through kept edges, into
  a few classes of connected cells. Only those matter.
- Everything ahead is untouched. Its effect on the frontier is the same for
  every tree, so it can be worked out once.

Restricting an inverse to some vertices is the same as inverting a Schur
complement, so $A$ only ever needs rows for the classes on the frontier.

**The part ahead.** For layer $s$, take the layers from $s$ on and tie each
cell of layer $s$ to the ground once for each edge it has back to layer
$s - 1$. Let $t_s$ be the number of spanning trees of that graph and
$N_s = t_s K_s$ its Green's function on layer $s$. Eliminating layer $s + 1$
gives a recurrence that runs from the last layer backwards:

$$N_s = t_s Q_s^{-1}, \qquad
Q_s = D_s + L_s + \left( F_s - \frac{E_s N_{s+1} E_s^{\mathsf T}}{t_{s+1}} \right),
\qquad t_s = t_{s+1} \det Q_s.$$

Here $L_s$ is the Laplacian of the edges inside layer $s$, $D_s$ and $F_s$ are
diagonal and count each cell's edges back and forward, and $E_s$ records which
cell of layer $s$ joins which of layer $s + 1$. The inversion is done by
fraction-free (Bareiss) elimination. A plain Bareiss run would let the numbers
grow by a factor of $t_{s+1}$ at each step; since every minor of $Q_s$ has
denominator exactly $t_{s+1}$, dividing that factor out once keeps them the
size of the answer.

**Bringing in a layer.** When the sweep reaches layer $s$, with $T = \tau K$
on the classes behind it and $C$ recording which class each cell of the layer
is tied to, the block-inverse formula gives the new matrix:

$$A = \begin{pmatrix} T & TP/t_s \\ \cdot & (\tau N_s + P^{\mathsf T} T P / t_s)/t_s \end{pmatrix},
\qquad P = C N_s.$$

Then the layer's edges are decided one by one as in section 4.

The cost is about $\sum_s (\text{size of layer } s)^3$ operations on integers
of roughly 1.6 bits per cell. For an $n \times m$ grid swept along its long
side that is $n m^3$ rather than the $(nm)^3$ of the direct method.

## 6. A shortcut for full grids

In a full grid every layer is the same path, with Laplacian $L$, and the
recurrence of section 5 only ever produces functions of $L$. Define
polynomials

$$q_n = 1, \qquad q_{n-1} = 1 + x, \qquad q_s = (2 + x)\, q_{s+1} - q_{s+2}.$$

Then with $U_s = q_s(L)$, an integer matrix,

$$t_s = \det U_s, \qquad K_s = U_{s+1} U_s^{-1}.$$

All these matrices commute with $L$. A matrix $F$ with $FL = LF$, for $L$
tridiagonal, is fixed by its first row:

$$F_{i+1,j} = F_{i,j-1} + F_{i,j+1} - F_{i-1,j} + (d_i - d_j) F_{i,j},$$

with $d$ the degrees along the path. So one linear solve per layer replaces a
full inversion, and only first rows need storing.

The count itself comes out directly: $U_0 - U_1 = \prod_i (L + \mu_i)$ over the
eigenvalues $\mu_i$ of the long-side path, and any cofactor of that matrix is
$\tau$.

## 7. From a message to an integer

**Numbering messages.** Order all byte strings by length, then
alphabetically, and number them $0, 1, 2, \dots$ A string $b$ of length $\ell$
gets

$$n(b) = \frac{256^{\ell} - 1}{255} + \sum_{i} b_i\, 256^{\ell - 1 - i}.$$

This is a bijection between byte strings and the natural numbers, so there is
no length field and no padding. A maze with $S$ states holds exactly the
strings numbered below $S$: every string of up to
$\lfloor \log_{256}(255 S + 1) \rfloor - 1$ bytes, and some one byte longer.

**Scrambling.** Small indices give degenerate trees: index 0 keeps every edge
it can, which draws a comb. So the message number goes through an affine map
first,

$$x = (a\, n + b) \bmod S, \qquad \gcd(a, S) = 1,$$

with $a$ and $b$ taken from a hash of the maze's shape and an optional seed.
It is a bijection of $0, \dots, S - 1$, undone with $a^{-1} \bmod S$. Over the
choice of seed, $x$ is uniform whatever the message is, so the maze is a
*uniform spanning tree*: the same distribution Wilson's algorithm draws, and
statistically an ordinary random maze. This is not encryption; it only makes
every message look typical.

## 8. States beyond the tree

A picture of a maze shows more than its tree, and whatever is free to choose
can carry data. The number of states $S$ is a product, and $x$ is split by
division with remainder.

- **Rectangle.** Two openings anywhere in an outer wall of $P = 2(n + m)$
  segments: $S = \tau \binom{P}{2}$. For $64 \times 64$ that adds 15 bits.
- **Custom map.** Cells are removed from the grid and the start and end are
  placed by hand, so only the tree carries data: $S = \tau$ for the graph of
  the cells that remain. That graph must be connected, and must contain a
  cycle, or else $\tau = 1$.
- **Circle.** The entrance can be any of the $c$ cells of the outer ring:
  $S = \tau c$.
- **Mixed map.** Several areas, each with its own tree, and one gate between
  each pair of neighbours, in any of the $\ell_j$ lanes that join them:
  $S = \prod_i \tau_i \prod_j \ell_j$.

## 9. The graphs

**Grid with cells removed.** The layers are the rows that still have cells.
The shortcut of section 6 no longer applies, so the general recurrence of
section 5 is used.

**Circle.** A centre cell and $R$ rings. Ring 1 has 6 cells, and ring $k$ has
twice as many as ring $k - 1$ whenever its cells would otherwise be wider than
one and a half ring depths, that is when $2\pi k / c_{k-1} > 1.5$. This gives
6, 12, 24, 24, 24, 48, … Each cell is joined to its two neighbours in the ring
and to the one cell inside it. The layers are the rings, each a cycle, and a
cell of one ring can have two cells of the next outside it. The count comes to
about 1.65 bits per cell.

**Mixed map.** Where a straight area faces a neighbour, its rows carry on as
lanes across the gap. The line between two lanes is a cubic Bézier curve that
leaves the area along its outward normal and arrives along the neighbour's,
landing on one stretch of the neighbour's outer wall per lane. Cutting each
lane into cells adds a block of cells to one side of the area. Graph-wise the
area is still a grid, with a corner cut out if it grows on two sides, so
section 5 applies unchanged; only the drawing is bent.

## 10. What it adds up to

| Maze | Cells | Bits | Bytes |
|---|---|---|---|
| 8×8 | 64 | 95.7 | 11 |
| 16×16 | 256 | 399.9 | 49 |
| 32×32 | 1024 | 1652.9 | 206 |
| 64×64 | 4096 | 6741.8 | 842 |
| Circle, 12 rings | 475 | 777.1 | 97 |
| Circle, 24 rings | 1819 | 3010.1 | 376 |

Schemes in the literature that hide bits along chosen paths of a maze reach
about 0.2 bits per cell (780 bits in a $64 \times 64$ maze). Using every
spanning tree gives the 1.64 above, which is the most a perfect maze of that
size can hold.

## References

- G. Kirchhoff, 1847: the matrix-tree theorem and effective resistance.
- C. J. Colbourn, R. P. J. Day, L. D. Nel, "Unranking and ranking spanning
  trees of a graph", *Journal of Algorithms* 10 (1989).
- E. H. Bareiss, "Sylvester's identity and multistep integer-preserving
  Gaussian elimination", *Mathematics of Computation* 22 (1968).
- R. Shrock, F. Y. Wu, "Spanning trees on graphs and lattices in d
  dimensions", *Journal of Physics A* 33 (2000).
- D. B. Wilson, "Generating random spanning trees more quickly than the cover
  time", STOC 1996.
- H.-L. Lee, C.-F. Lee, L.-H. Chen, "A perfect maze based steganographic
  method", *Journal of Systems and Software* 83 (2010).
- H. Lakhani, F. Zaffar, "Covert channels in online rogue-like games", ICC
  2014.
