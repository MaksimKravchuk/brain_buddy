# PR dependency graph

Authoritative edges and ownership: [tasks.md](tasks.md). Each node is one task and one atomic PR. An arrow means the prerequisite must be accepted and merged before the dependent worker starts. Node numbers are stable identifiers, not a serial schedule. Start every ready independent node up to the available worker limit; land through the repository’s serialized gate.

```mermaid
flowchart TD
  P01["PR-01 · Contract / flag OFF"]
  P02["PR-02 · Oracle inputs"]
  P03["PR-03 · Rust codecs"]
  P61["PR-61 · Domain values"]
  P06["PR-06 · Text / calendar"]
  P04["PR-04 · Python bridge"]
  P05["PR-05 · Apple bridge"]
  P08["PR-08 · Projects / tags"]
  P09["PR-09 · Archive"]
  P10["PR-10 · Children"]
  P13["PR-13 · Formulation"]
  P07["PR-07 · Task lifecycle"]
  P11["PR-11 · Smart Add"]
  P12["PR-12 · Queries"]
  P14["PR-14 · Park / yield"]
  P15["PR-15 · Review decisions"]
  P16["PR-16 · Review sessions"]
  P20["PR-20 · Job ledger"]
  P47["PR-47 · AI policy"]
  P62["PR-62 · Domain registration"]
  P17["PR-17 · Apple facade"]
  P18["PR-18 · Python Task facade"]
  P19["PR-19 · Python Review facade"]
  P21["PR-21 · Fence authority"]
  P22["PR-22 · Review jobs"]
  P23["PR-23 · Privacy / voice jobs"]
  P24["PR-24 · Agent jobs"]
  P64["PR-64 · Scheduler handoff"]
  P25["PR-25 · Aggregate UoW"]
  P26["PR-26 · Receipts / feed"]
  P27["PR-27 · Legacy Task adapter"]
  P28["PR-28 · Review / consent adapter"]
  P29["PR-29 · Remaining writers"]
  P30["PR-30 · Current authority"]
  P31["PR-31 · Commands / wire"]
  P32["PR-32 · Delta / transfers"]
  P33["PR-33 · Snapshots"]
  P58["PR-58 · SSE"]
  P63["PR-63 · Route registration"]
  P34["PR-34 · Client storage"]
  P35["PR-35 · Local execute"]
  P36["PR-36 · Replay / issues"]
  P37["PR-37 · Feed / receipts"]
  P38["PR-38 · Snapshot activation"]
  P39["PR-39 · Sync session"]
  P40["PR-40 · Transport"]
  P41["PR-41 · Store import"]
  P42["PR-42 · Outbox import"]
  P43["PR-43 · Workspace"]
  P44["PR-44 · Account lifecycle"]
  P45["PR-45 · iPhone recovery"]
  P46["PR-46 · Mac recovery"]
  P48["PR-48 · Server AI"]
  P49["PR-49 · Shared native AI"]
  P59["PR-59 · iPhone AI"]
  P60["PR-60 · Mac AI"]
  P50["PR-50 · Retention"]
  P51["PR-51 · Export / purge"]
  P52["PR-52 · Restore"]
  P53["PR-53 · Web parity"]
  P54["PR-54 · Apple / SQLite pilot"]
  P55["PR-55 · PostgreSQL adapter"]
  P56["PR-56 · Migration rehearsal"]
  P57["PR-57 · PostgreSQL cutover"]
  P01 --> P02
  P01 --> P03
  P03 --> P61
  P02 --> P06
  P61 --> P06
  P06 --> P04
  P04 --> P05
  P06 --> P08
  P08 --> P09
  P06 --> P10
  P06 --> P13
  P13 --> P07
  P07 --> P11
  P08 --> P11
  P13 --> P12
  P13 --> P14
  P07 --> P15
  P10 --> P15
  P14 --> P15
  P12 --> P16
  P13 --> P16
  P01 --> P20
  P06 --> P47
  P61 --> P47
  P09 --> P62
  P11 --> P62
  P12 --> P62
  P15 --> P62
  P16 --> P62
  P47 --> P62
  P05 --> P17
  P62 --> P17
  P04 --> P18
  P62 --> P18
  P18 --> P19
  P19 --> P21
  P20 --> P21
  P21 --> P22
  P21 --> P23
  P21 --> P24
  P22 --> P64
  P23 --> P64
  P24 --> P64
  P64 --> P25
  P25 --> P26
  P26 --> P27
  P27 --> P28
  P28 --> P29
  P29 --> P30
  P30 --> P31
  P31 --> P32
  P32 --> P33
  P31 --> P58
  P33 --> P63
  P58 --> P63
  P05 --> P34
  P62 --> P34
  P34 --> P35
  P35 --> P36
  P36 --> P37
  P37 --> P38
  P38 --> P39
  P39 --> P40
  P63 --> P40
  P40 --> P41
  P41 --> P42
  P17 --> P43
  P42 --> P43
  P43 --> P44
  P44 --> P45
  P44 --> P46
  P29 --> P48
  P47 --> P48
  P44 --> P49
  P47 --> P49
  P48 --> P49
  P49 --> P59
  P49 --> P60
  P33 --> P50
  P48 --> P50
  P42 --> P51
  P50 --> P51
  P51 --> P52
  P18 --> P53
  P45 --> P54
  P46 --> P54
  P49 --> P54
  P52 --> P54
  P53 --> P54
  P59 --> P54
  P60 --> P54
  P54 --> P55
  P55 --> P56
  P56 --> P57
```

The PR-62 and PR-63 joins only register already tested modules/routes. They may not absorb unfinished business logic. PR-64 owns the bounded worker loop and scheduler handoff; the independent adapter PRs keep the old schedulers active until it passes. PR-54 is the Apple/current-SQLite acceptance gate; PR-55…57 remain a separately authorized post-pilot migration.
