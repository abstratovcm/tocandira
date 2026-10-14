# engine/nokamute

Git submodule: https://github.com/abstratovcm/nokamute, branch `tocandira`, a fork of
https://github.com/edre/nokamute (MIT, Eric Roshan Eisner).

What is whose: the board representation, move generator, UHP plumbing and the alpha beta
search (his generic `minimax` crate) are nokamute's. tocandira replaces the evaluation and,
later, the search. Strength claims always name nokamute's search as the search.

Branches in the fork:
- `search-command`: upstream master plus the UHP `search` command (move;score;pvlen),
  offered upstream as edre/nokamute#13.
- `tocandira`: engine development, starts from `search-command`. The learned evaluation
  lands here.

The frozen opponent is never taken from this fork: `scripts/build_reference.sh` builds
upstream `v1.0.3` into `reference/`.

After cloning tocandira: `git submodule update --init`, then build the engine
(see README). To pull upstream fixes into the fork: fetch `upstream` in the fork clone,
rebase `tocandira` on it, push, then bump the submodule here.
