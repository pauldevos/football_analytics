# 09b — Systematic Crawl of John Turney's Pro Football Journal (2026-08-23)

Companion to `09_dl_technique_research_pilot_20260823.md` (owned by a parallel task — not
edited here). That doc's prior pass read 4 posts (Best Nose Tackles, Top 3-4 DEs, Top 4-3
DEs, Top 4-3 DTs) and found them unusually rich in sourced technique labels. This pass
systematically crawled the rest of the blog (nflfootballjournal.blogspot.com) via its
Blogger sitemap, plus followed up on other researchers/sources Turney cites.

## Method

The blog's `sitemap.xml` (4 paginated sub-sitemaps, fetched directly with `curl`, not
through the summarizing WebFetch tool) yielded **2,460 unique post URLs**, spanning
2012-01 through 2026-08. Grepped that full URL list for DL/technique keywords (technique,
nose tackle, 4-3, 3-4, sack, pass-rush, etc.), the pilot's named-star list (Lilly, Olsen,
Greene, Page, White, Culp, Randle, Kennedy, Sapp, Donald), the pilot's 12 team names
combined with line/tackle/end, and known DL-adjacent figures (Youngblood, Deacon Jones,
Fearsome Foursome). That produced a shortlist of ~35 candidate posts, of which **33 were
fetched and extracted** (see below). This is not exhaustive of all 2,460 posts — see
Diminishing Returns — but covers essentially everything the keyword sweep surfaced as
DL/technique-relevant.

## Part 1: New Data From Turney's Broader Archive

### Scheme/technique history posts (18 posts)

- **"4-3 Defensive Ends on the Nose" (2023)** — Claude Humphrey (1971, 3-man line),
  Bubba Smith ("usually a left DE, playing RDT in overshift"), Deacon Jones ("on the
  nose in a five-man line"), Lyle Alzado (five-man line), Cedrick Hardman ("cocked on
  the center in a five-man line"), Dan Hampton (nose in 46, RDT in base/nickel, DE
  1979-81), Howie Long (DE in 3-4, 3-technique in nickel, nose in 46 and 3-3-5).
- **"Deacon Jones — R5 and L5" (2018)** — Jones on special-teams kickoff-coverage
  spots (R5/L5), 1964, evidence of exceptional speed for a 260-lb lineman.
- **"Deacon Jones' Stance in Early Years" (2021)** — stance evolution: 1961 right-hand
  down/low tail; 1962-63 left-hand-down "track" stance; 1964-on right-hand-down track
  stance, coincident with adopting the head-slap as a primary move (learned from Rosey
  Grier).
- **"Elvin Bethea and Deacon Jones — Washouts at Left Offensive Tackle" (2018)** — both
  HOF DEs (Jones, LA Rams 1961; Bethea, Houston Oilers 1968) were tried at left OT
  early and failed before moving to DE.
- **"Merlin Olsen — Best I Ever Saw" (2014)** — 2008 Turney interview; Olsen's own
  peer comparisons: "Joe Greene would be my left tackle and Bob Lilly would be on the
  right... Joe and I were kind of similar and Bob and Alan Page were similar." No
  technique label for Olsen himself, but a rare direct player-sourced pairing of
  Lilly/Page as stylistically similar and Greene/Olsen as similar.
- **"Jack Youngblood: I Retired Because I Was..." (2017)** — LA Rams, 1983-84 in the
  3-4: 5-technique and 6-technique under Shurmur's numbering (equiv. 4-/5-tech
  traditional), 92% of snaps (1983), 10.5 sacks (1983)/9.5 (1984), Proscout ranked him
  13th (1983)/12th (1984) among DL. Sources: John Robinson, Fritz Shurmur, Marv Goux.
- **"Who Was the NFL's First Fearsome Foursome?" (2018)** — traces the nickname:
  NYG 1959 (Katcavage/Grier/Modzelewski/Robustelli), SD 1961 (Faison/Ladd/Hudson/Nery),
  Detroit 1961 (McCord/Karras/Brown/Williams), Dallas 1964
  (Andrie/Lilly/Colvin/Stephens, briefly, before "Doomsday"), then LA Rams as the
  version that stuck: 1963-66 (Jones-LE/Olsen-LT/Grier-RT/Lundy-RE), 1967-69
  (Grier→Roger Brown), 1974 "New Fearsome Foursome" (Youngblood/Olsen/Brooks/Dryer).
- **"Rosey Grier Showing Deacon Jones How To..." (2023)** — head-slap technique
  provenance: Grier using it regularly 1960-62 (before Jones' 1963 Rams arrival),
  Jones adopting it as a primary move only from 1964 on; other adopters named: Claude
  Humphrey, Carl Eller, Rich "Tombstone" Jackson, Jack Youngblood.
- **"The 1951 Rams' Foray Into 4-3 Defense" (2020)** — Rams ran base 5-2, switched to
  a situational 4-3 against Green Bay's spread passing attack; players named: Don
  Paul, Tank Younger, Stan West, rookie Andy Robustelli at RDE.
- **"When Rams Are in Base Defense, Which 3-4..." (2019)** — 2018 Rams personnel:
  Ndamukong Suh at nose, Aaron Donald at 3-technique (weak side), Michael Brockers at
  5-technique (strong side).
- **"LA Rams All-Time 3-4 Top Seasons" (2020)** — by role: ends — Youngblood
  1983-84 (~47 tkl/10 sacks avg), Dante Fowler 2019 (11.5 sacks); 3-technique — Aaron
  Donald 2017-19 (avg 15 sacks/9 stuffs/49 tkl/4 FF); **4i-technique — Reggie Doss**
  1983-84 (66 tkl, 8 TFL, 8.5 sacks); nose — Alvin Wright 1988-90, Greg Meisner 1984.
- **"Where [a] Rams Defensive Tackle Ranks..." (2025)** — historical DT ranking:
  Donald 2014, Kobie Turner 2023, Braden Fiske 2024, Dick Huffman 1947, Olsen 1962,
  Larry Brooks 1972, Sean Gilbert 1992, Jim Winkler 1951, Frank Fuller 1953, Brockers
  2012. Quotes from Howard Cosell (on Brooks) and Tex Schramm (on Winkler).
- **"That's a Tall 3-4 Defensive Line" (2018)** — 1975 Chiefs front, avg 6'7": John
  Matuszak (LE, 6'8"), Buck Buchanan (nose, 6'7"), Wilbur Young (RE, 6'6"). Notes Art
  Still (6'7") continuing the pattern from 1978.
- **"Splitting Hairs on Defensive Tackles" (2020, all-2010s-decade rankings)** —
  by sub-role: "sink end/30 end/power end" (Watt, Campbell, Heyward); **3-technique**
  (Donald, Geno Atkins, Gerald McCoy); **"40 tackle"** (Fletcher Cox, Suh, Kyle
  Williams); **shade/nose** (Damon Harrison, Linval Joseph). Direct quote: Cox is
  "technically perfect... reminds us of Bob Lilly/Joe Greene combo."
- **"A 1970s-Type Defensive End Excelling in..." (Aaron Schobel, 2022)** — Turney
  compares Schobel's build/style to Gino Marchetti, Youngblood, Jim Marshall; Belichick
  quote on his technique ("several good moves... explosive power").
- **"Sack Master Coach — Floyd Peters" (2018)** — DL coach across Dolphins, Giants,
  49ers ("Gold Rush" '76), Lions ("Silver Rush" '78, Bubba Baker 23 sacks), Cardinals,
  Vikings (moved Chris Doleman from LB to DE, moved Keith Millard to 3-technique in a
  "flop" 4-3 — Millard's 1989 DPOY season), Bucs (3-4→4-3 conversion), Raiders. Direct
  Peters quote on repositioning Doleman to get him on the field in nickel.
- **"The 1976-77 Chiefs Defensive Line" (2024)** — Wilbur Young (RDE), Whitney Paul
  (LDE, 10th-round 1976 pick), Matuszak's 1975 departure; Marv Levy's 1978 shift to a
  3-4 and drafting Art Still. Paul Zimmerman quoted on Young: "moved inside for the
  injured Louie Kelcher and found a home" (re: Young's earlier Chargers stint).
- **"Raiders Defensive Ends Mt. Rushmore" (2024)** — Howie Long (two-gap 3-4 end,
  also 3-technique in "Bandit/Pirate/Desperado" nickel packages), Maxx Crosby, Ike
  Lassiter (1965-69), Greg Townsend (107.5 sacks, franchise record).

### "Worth Remembering" single-player series (8 posts) — confirms this is a real,
recurring dedicated-profile format beyond the 6 the parent doc already found:

- **Patrick Kerney** (Falcons/Seahawks) — career sack/snap data, no explicit technique
  label beyond position (DE).
- **Aaron Kampman** (Packers/Jaguars) — sack-by-season, Zimmerman All-Pro 2007, PFF
  pressure ranking.
- **Jeff Lageman** (Jets/Jaguars) — moved from college ILB to Jets rush backer; **Jets
  switched from 3-4 to Pete Carroll's 4-3 "Eagle" defense in 1991**, modeled on the
  Vikings defense under Floyd Peters.
- **Marvin Washington** (Jets/49ers/Broncos) — alignments: LDE, RDE, **3-technique
  tackle**, nickel rusher. Quote from DL coach Greg Robinson comparing him to Lageman
  ("bigger, stronger... more physical").
- **Michael Sinclair** (Seahawks) — nickel rusher 1993-98; **"5-technique" (2000,
  tighter alignment)**; preferred "wide 9" split-end positioning.
- **Kevin Carter** (Rams/Titans/Dolphins/Bucs) — RDE (1995 preseason)→LDE (regular
  season)→DT on passing downs (2000+). Rich Brooks: "a bigger Chris Doleman-type."
- **Neil Smith** (Chiefs/Broncos/Chargers) — played weak-side DL, left side regardless
  of TE alignment (1992-93 on); unnamed scout quotes on his get-off and leverage.
- **Ross Browner** (Bengals) — RDE in a 4-3 (1978-79), then RDE in a 3-4 (1980-86):
  "push a blocker back, read the play, then make a move."

### Other individual DL profiles (3 posts)

- **Fred Miller** (Colts, 1962-72, RIP tribute) — DT, 52 career sacks, Bill Curry and
  DL coach John Sandusky quotes; no explicit technique label.
- **Jumpy Geathers** (Saints/Washington/Falcons/Denver) — DE (1984-85, 13.5 sacks) →
  moved inside to DT/nickel (1986, 9 sacks). Signature "forklift" move described in
  detail by Geathers himself and victims (Randy Cross, Nate Newton).
- **Fred Smerlas** (Bills nose tackle) — explicit **"two-gap alignment specialist in
  3-4"**, described as attacking centers rather than "catching" blocks. Dwight
  Stephenson and Jim McNally quotes on how hard he was to block one-on-one.

### Confirmed as duplicates of already-known posts (not re-extracted in depth)

Fred Dryer, Mike Bell, Otis Sistrunk, Fred Cook, William Fuller, and Neil Smith all have
dedicated posts exactly as the parent doc's prior pass found — this crawl found the same
URLs, no additional distinct posts on those six players.

## Part 2: Other Sources Discovered

**Turney's own posts about other researchers** (fetched directly, 4 posts):
- **"Joel Buchsbaum — A Pioneer Draftnik" (2018)** — confirms Buchsbaum published
  primarily via *Pro Football Weekly* and Gannett News Service (from 1979); credits him
  with coining "defensive middle" (grouping nose/4-3 tackles, 1991) and popularizing
  "outside defensive linemen" (modern "edge"). **No online archive of Buchsbaum's
  original PFW columns was found or referenced** — his work exists only in the
  reproduced-image excerpts on Turney's own post.
- **"RIP Dr. Z — Friend and Mentor" (2018)** — a personal memoir, not a technique
  resource; no SI archive links included.
- **"Proscout Inc: This Era's Top Players Not Yet..." (2019)** — explains Proscout's
  Blue/Red color-grade system with real examples (Richard Seymour graded "blue at both"
  5-technique and 3-technique; Fred Smerlas blue early-80s and late-80s; Charles Mann
  single-digit rank 7 times). **No public Proscout archive** — Turney states Proscout
  still operates (now run by Giddings' son) but its grades are not published; Turney
  only discusses them ~5-10 years after a player retires.
- **"RIP Mike Giddings — an NFL Pioneer" (2023)** — Giddings invented the Blue/Red/
  Purple grading language and terms like "shutdown corner," "edge rusher," "designated
  pass rusher" (per Charles Davis quote). No DL-specific grading detail or archive link.

**Independent sources found via web search (not Turney citations, followed up directly):**

- **Sports Illustrated — "Dr. Z's All-Time Team: Part II — Defense" (2016, SI.com,
  still live)**: this is a genuinely independent, high-value find — it directly
  supplies technique data for **three of the pilot's named stars that Turney's blog
  itself has no dedicated post for**: **Bob Lilly** ("grabber and thrower"),
  **Merlin Olsen** ("quintessential bull rush tackle"), and **Joe Greene** (Steelers'
  "Cocked Nosetackle" alignment — Greene "attacked the center-guard gap from an
  angle"). Also Reggie White (power-side DE, "hump move"), Howie Long, Mark Gastineau,
  Pat Williams ("play the nose... move outside the guard in the three-technique"),
  Ernie "Fats" Holmes. Confidence: **High** — Zimmerman was a credentialed, technically
  literate original source, and this is his own published, still-hosted work, not a
  secondhand citation. General search also surfaced a second SI/Zimmerman passage
  explaining the zero-technique/two-gap vs. three-technique/one-gap distinction and the
  "reduced end" concept directly — worth a full read in a follow-up pass if this doc's
  scope expands.
- **PFRA "Coffin Corner" archive (profootballresearchers.com)** — confirmed the archive
  exists with year-indexed pages (1985-2025) and at least one directly-linked PDF
  (`16-04-570.pdf`, a 1994 "First 25 Years" retrospective) appeared in search results
  unauthenticated. However, fetching the 1985 index page directly returned **HTTP 403
  Forbidden** — access is inconsistent, not a clean workaround. Confirms the parent
  pilot's finding that this source hits real access blocks; a further Wayback Machine
  attempt was not made this pass (time-boxed) but is the next thing to try before
  giving up on Coffin Corner entirely.
- **Curley Culp / Super Bowl IV nose-tackle origin story** — well-documented across
  Wikipedia, Houston Chronicle (John McClain), and others: Hank Stram lined Culp
  head-up on Vikings center Mick Tingelhoff in Super Bowl IV specifically to negate
  Minnesota's outside rush, which is frequently cited as a founding moment for the
  modern 3-4 head-up/two-gap nose tackle. This directly answers Culp's entry on the
  named-star list even though no Turney post covers him individually. Confidence:
  **Medium-High** — widely corroborated but not from a single primary technical source.
- **brophyfootball.blogspot.com — "Coaching the 2-Gap Nose"** — a second technique-
  focused football blog surfaced in the Culp search, distinct from Turney's. Not
  explored beyond the search snippet this pass; flagged as a candidate for a future
  focused pass, not confirmed high-value yet.
- **TheRamsHuddle forum** reappeared in search results (a thread quoting Zimmerman's
  unpublished All-Time Team notes), consistent with the parent doc's earlier finding
  that Rams-specific forums carry unusually deep technique detail — not re-mined this
  pass since the parent doc already covered a Youngblood thread there.

No independently accessible archive of Buchsbaum's or Proscout's *original* material
was found anywhere (not just on Turney's blog) — both appear to survive publicly only
through secondhand citation (Turney's posts, occasional other writers), not as a
browsable primary archive.

## Part 3: Honest Diminishing-Returns Assessment

**The broader crawl was worth doing, but the return curve is not flat — it's front-
loaded and drops fast.**

What it added, concretely: confirmed technique/alignment labels or role descriptions
for roughly **45-50 additional players** across 33 posts (vs. the ~60+ "other teams"
mentions the parent doc found across just 4 "Top N" list posts). Several finds are
genuinely load-bearing for the pilot's stated goals:
- Multiple explicit team-scheme histories for **Rams** (a pilot team) across six
  different eras (1951, 1963-69, 1974, 1983-90, 2017-19), which is more scheme
  continuity than any other single team in this crawl.
- A confirmed, recurring **single-player-profile format** ("Worth Remembering") that
  reliably carries alignment detail — 8 more instances found, following the same
  pattern the parent doc flagged as high-yield.
- Specific "4i-technique" and "cocked nose" and "flop 3-technique" labels that don't
  appear in the 4 originally-read "Top N" posts at all — i.e., the ranked list format
  and the narrative/profile format surface genuinely different technique vocabulary,
  so both are needed.

Where it hit real limits:
- **The 4 keyword-relevant "Top N" posts already read remain the single highest
  density source** — each one is *built* around technique labels as its organizing
  principle. Everything else found here is technique data as a side effect of a
  biographical or historical narrative, so extraction yield per post is meaningfully
  lower (most posts here gave 1-3 clean data points; the original 4 gave dozens each).
- **Coverage of the specific named-star list stayed thin even after a full-blog sweep.**
  Of the 10 named stars, only Olsen, Sapp, and Donald have dedicated Turney posts;
  Lilly, Page, White, Culp, Randle, and Kennedy have **no dedicated Turney post at
  all** — they only appear as passing comparisons inside other players' posts (Olsen
  comparing himself to Lilly/Page/Greene; the SI Dr. Z piece independently covering
  Lilly/Olsen/Greene). For those six players, Turney's blog specifically is close to
  exhausted; the Dr. Z SI piece is the better source now.
- **The sitemap itself (2,460 posts) is dominated by non-DL content** — team uniforms,
  weekly Packers game recaps, Hall of Fame voting commentary, all-decade offensive
  teams. The keyword sweep is doing real work filtering this down to ~1.4% of the
  corpus; a blind post-by-post read of the full archive would have been mostly waste.

**Bottom line:** mining the full archive (not just 4 posts) was the right call and
should be considered largely done for DL/technique purposes — the keyword-filtered
sweep found essentially everything on-topic the blog has to offer, and further posts
beyond this list are increasingly likely to be duplicates, off-topic, or single-fact
mentions not worth a dedicated fetch. The better next move for closing the remaining
named-star gaps (Lilly, Page, White, Culp, Randle, Kennedy) is not more Turney posts —
it's the Dr. Z SI archive (confirmed still live, confirmed to cover exactly this gap)
and a focused pass on team-specific forums (Rams Huddle-style) for the other pilot
teams, following the pattern that already worked once.

## Sources

- https://nflfootballjournal.blogspot.com/sitemap.xml (pages 1-4, 2,460 posts enumerated)
- All 33 individual post URLs cited inline above
- https://www.si.com/nfl/2016/06/30/dr-z-paul-zimmerman-memoirs-alltime-team-defense-special-teams
- https://profootballresearchers.com/coffin-corner-1985.html (403 on direct fetch)
- https://en.wikipedia.org/wiki/Curley_Culp ; Houston Chronicle (John McClain, Culp obituary)
- http://brophyfootball.blogspot.com/2015/12/coaching-2-gap-nose.html (unexplored lead)
