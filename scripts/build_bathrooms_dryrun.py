#!/usr/bin/env python3
"""Build testing/bathrooms-dryrun.html from live bathrooms.html.

Goals:
- Same funnel UX as live bathrooms
- Full new routing: exact adset → CDN expanded → B2B exact Location → B2B CDN
- Zero Airtable writes (client locks + GET-only proxy path)
- Visible decision log after submit
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path("/root/projects/thelocalpick")
SRC = ROOT / "bathrooms.html"
OUT = ROOT / "testing" / "bathrooms-dryrun.html"

HEAD_INJECT = """
    <meta name="robots" content="noindex, nofollow">
    <base href="/">
    <style id="tlp-dryrun-banner-css">
      #tlp-dryrun-banner {
        position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
        background: #7a1f1f; color: #fff; font: 700 13px/1.35 Arial, sans-serif;
        text-align: center; padding: 8px 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,.25);
      }
      #tlp-dryrun-banner code { background: rgba(255,255,255,.15); padding: 1px 5px; border-radius: 3px; }
      body { padding-top: 42px !important; }
      #tlp-dryrun-panel {
        position: fixed; right: 12px; bottom: 12px; width: min(440px, calc(100vw - 24px));
        max-height: min(55vh, 520px); overflow: auto; z-index: 99998;
        background: #0b1220; color: #e8eefc; border: 1px solid #334155; border-radius: 10px;
        box-shadow: 0 10px 30px rgba(0,0,0,.35); font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
        display: none;
      }
      #tlp-dryrun-panel .hd {
        position: sticky; top: 0; background: #111827; padding: 10px 12px; border-bottom: 1px solid #334155;
        display: flex; justify-content: space-between; gap: 8px; align-items: center;
      }
      #tlp-dryrun-panel .hd strong { color: #fbbf24; font-size: 12px; }
      #tlp-dryrun-panel .hd button {
        background: #1f2937; color: #e5e7eb; border: 1px solid #475569; border-radius: 6px;
        padding: 4px 8px; cursor: pointer; font: inherit;
      }
      #tlp-dryrun-panel pre {
        white-space: pre-wrap; word-break: break-word; margin: 0; padding: 12px; color: #dbeafe;
      }
      #tlp-dryrun-panel .ok { color: #86efac; }
      #tlp-dryrun-panel .warn { color: #fcd34d; }
    </style>
"""

BANNER_HTML = """
    <div id="tlp-dryrun-banner">
      DRY-RUN BATHROOMS — full live funnel + new routing · <strong>NO Airtable writes</strong> ·
      Meta pixel off · proxy is GET-only · decision log appears after Get Estimate
    </div>
    <div id="tlp-dryrun-panel" aria-live="polite">
      <div class="hd">
        <strong>DRY-RUN decision log</strong>
        <span>
          <button type="button" id="tlp-dryrun-copy">Copy</button>
          <button type="button" id="tlp-dryrun-hide">Hide</button>
        </span>
      </div>
      <pre id="tlp-dryrun-log">Waiting for submit…</pre>
    </div>
"""

BOOT_SCRIPT = r"""
    <script>
    // Hard locks BEFORE any funnel JS runs.
    window.__TLP_TESTING_MODE__ = true;
    window.__TLP_DRY_RUN__ = true;
    window.__TLP_DRY_RUN_WRITE_BLOCKS__ = 0;
    window.__TLP_LAST_DECISION_LOG__ = '';
    window.TLP_DEBUG_VERBOSE = true;

    (function hardenFetch() {
      const originalFetch = window.fetch.bind(window);
      window.__TLP_ORIGINAL_FETCH__ = originalFetch;
      window.fetch = async function(input, init) {
        const req = (input instanceof Request) ? input : null;
        const method = String((init && init.method) || (req && req.method) || 'GET').toUpperCase();
        let url = '';
        try {
          url = String(req ? req.url : input);
        } catch (_) {
          url = String(input);
        }
        const isAirtable = /\/api\/airtable/i.test(url) || /api\.airtable\.com/i.test(url);
        if (isAirtable && method !== 'GET' && method !== 'HEAD') {
          window.__TLP_DRY_RUN_WRITE_BLOCKS__ += 1;
          console.error('[DRY-RUN] BLOCKED Airtable write', method, url);
          return new Response(JSON.stringify({
            error: 'DRY_RUN_WRITE_BLOCKED',
            method,
            url,
            message: 'Bathrooms dry-run page forbids Airtable writes'
          }), {
            status: 403,
            headers: { 'Content-Type': 'application/json' }
          });
        }
        // Rewrite live proxy path → GET-only dry-run proxy
        if (/\/api\/airtable(\/|$)/i.test(url) && !/\/api\/airtable-readonly(\/|$)/i.test(url)) {
          url = url.replace(/\/api\/airtable(\/|$)/i, '/api/airtable-readonly$1');
          if (req) {
            return originalFetch(new Request(url, req), undefined);
          }
          return originalFetch(url, init);
        }
        return originalFetch(input, init);
      };
    })();

    // Kill Meta pixel early
    window.fbq = function(){ console.log('[DRY-RUN] fbq skipped', arguments); };
    </script>
"""

PANEL_HELPER = r"""
        function tlpShowDryRunLog(text) {
            try {
                window.__TLP_LAST_DECISION_LOG__ = String(text || '');
                const panel = document.getElementById('tlp-dryrun-panel');
                const pre = document.getElementById('tlp-dryrun-log');
                if (pre) pre.textContent = window.__TLP_LAST_DECISION_LOG__;
                if (panel) panel.style.display = 'block';
                console.log('[DRY-RUN DECISION LOG]\n' + window.__TLP_LAST_DECISION_LOG__);
            } catch (e) {
                console.warn('tlpShowDryRunLog failed', e);
            }
        }
        document.addEventListener('DOMContentLoaded', () => {
            const hide = document.getElementById('tlp-dryrun-hide');
            const copy = document.getElementById('tlp-dryrun-copy');
            if (hide) hide.addEventListener('click', () => {
                const panel = document.getElementById('tlp-dryrun-panel');
                if (panel) panel.style.display = 'none';
            });
            if (copy) copy.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(window.__TLP_LAST_DECISION_LOG__ || '');
                    copy.textContent = 'Copied';
                    setTimeout(() => { copy.textContent = 'Copy'; }, 1200);
                } catch (_) {}
            });
        });
"""

# New routing block replaces from routingWeeklyRemaining through end of computeLeadRoute
NEW_ROUTING = r'''
        // ============================================================
        // DRY-RUN ROUTING (2026-08-04 locked product rules)
        // Exact Active adset → CDN expanded Active adset →
        // B2B exact Location ZIP (random ties) → B2B CDN neighbors
        // No weekly/monthly capacity in matcher. No national B2B random.
        // ============================================================
        function routingBoolLabel(v) {
            return v ? 'yes' : 'no';
        }

        const GEO_NEIGHBOR_BASE = 'https://geo.thelocalpick.com/zip-neighbors-30mi/by-zip';
        const GEO_MAX_MILES = 30;
        const GEO_MAX_NEIGHBORS = 25;
        const B2B_TABLE_ID = 'tbldNpwtCN9y5Pkiy';
        const B2B_CREATED_AFTER = '2025-09-02T00:00:00.000Z';
        const B2B_NICHE_ALIASES = {
            bathrooms: ['bathrooms', 'bathroom', 'bath', 'bath remodeling', 'bathroom remodeling'],
        };
        let b2bPoolCache = null; // { byZip: Map, qualifiedCount, fetched, pages, loadedAt }

        function routingWeeklyRemaining(adsetFields) {
            // Capacity intentionally ignored in matcher (automation-owned).
            return true;
        }

        function routingMonthlyRemaining(adsetFields) {
            return true;
        }

        /** Eligible = niche + Active client + Active adset only (no capacity tiers). */
        function routingComputeTier(clientRec, adsetFields) {
            if (!clientRec || !adsetFields) return 0;
            if (!routingAdsetNicheMatchesFunnel(adsetFields)) return 0;
            if (!routingIsClientActive(clientRec, adsetFields) || !routingIsAdsetActive(adsetFields)) return 0;
            return 1;
        }

        function routingDedupeCandidatesByAdset(phase1Rows) {
            const seen = new Map();
            for (const row of phase1Rows) {
                if (!row.adsetId || !row.clientRec || !row.adsetRec) continue;
                if (!seen.has(row.adsetId)) seen.set(row.adsetId, row);
            }
            return [...seen.values()];
        }

        /** Oldest junction Linked-at / createdTime among eligible Active partners. */
        function routingPickPartnerFromPool(candidateRows) {
            const ranked = [];
            for (const row of candidateRows) {
                const af = row.adsetRec && row.adsetRec.fields;
                if (!af) continue;
                const tier = routingComputeTier(row.clientRec, af);
                if (tier < 1) continue;
                ranked.push({
                    tier,
                    adsetId: row.adsetId,
                    clientRec: row.clientRec,
                    adsetRec: row.adsetRec,
                    junctionId: row.junctionId,
                    linkCreated: row.linkCreated,
                    matchedZip: row.matchedZip || null,
                    matchedZipRec: row.matchedZipRec || null,
                    distanceMi: row.distanceMi == null ? null : row.distanceMi,
                });
            }
            if (!ranked.length) return null;
            ranked.sort((a, b) => {
                const ta = Date.parse(a.linkCreated) || 0;
                const tb = Date.parse(b.linkCreated) || 0;
                if (ta !== tb) return ta - tb;
                const ca = Date.parse(a.clientRec && a.clientRec.createdTime) || 0;
                const cb = Date.parse(b.clientRec && b.clientRec.createdTime) || 0;
                return ca - cb;
            });
            return ranked[0];
        }

        function routingPickClosestThenOldest(candidateRows) {
            const ranked = [];
            for (const row of candidateRows) {
                const af = row.adsetRec && row.adsetRec.fields;
                if (!af) continue;
                if (routingComputeTier(row.clientRec, af) < 1) continue;
                ranked.push({
                    tier: 1,
                    adsetId: row.adsetId,
                    clientRec: row.clientRec,
                    adsetRec: row.adsetRec,
                    junctionId: row.junctionId,
                    linkCreated: row.linkCreated,
                    matchedZip: row.matchedZip || null,
                    matchedZipRec: row.matchedZipRec || null,
                    distanceMi: row.distanceMi == null ? null : Number(row.distanceMi),
                });
            }
            if (!ranked.length) return null;
            ranked.sort((a, b) => {
                const da = a.distanceMi == null ? 9999 : a.distanceMi;
                const db = b.distanceMi == null ? 9999 : b.distanceMi;
                if (da !== db) return da - db;
                const ta = Date.parse(a.linkCreated) || 0;
                const tb = Date.parse(b.linkCreated) || 0;
                return ta - tb;
            });
            return ranked[0];
        }

        async function routingLoadNeighbors(zipFive, traceStep) {
            const url = `${GEO_NEIGHBOR_BASE}/${encodeURIComponent(zipFive)}.json`;
            const t0 = Date.now();
            let res;
            try {
                res = await fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store' });
            } catch (e) {
                traceStep(`[CDN] error: ${e && e.message ? e.message : e}`);
                return [];
            }
            if (res.status === 404) {
                traceStep(`[CDN] no neighbor pack for ${zipFive}`);
                return [];
            }
            if (!res.ok) {
                traceStep(`[CDN] HTTP ${res.status} for ${zipFive}`);
                return [];
            }
            const data = await res.json();
            const neighbors = Array.isArray(data.neighbors) ? data.neighbors : [];
            const out = [];
            for (const n of neighbors) {
                const mi = Number(n.mi);
                if (!Number.isFinite(mi) || mi > GEO_MAX_MILES + 1e-9) continue;
                const z = zipRouteNormalizeZipFive(n.zip);
                if (!/^\d{5}$/.test(z)) continue;
                out.push({ zip: z, rec: n.rec || null, mi });
                if (out.length >= GEO_MAX_NEIGHBORS) break;
            }
            traceStep(
                `[CDN] neighbors file=${neighbors.length} using=${out.length} within ${GEO_MAX_MILES}mi ` +
                `(${((Date.now() - t0) / 1000).toFixed(2)}s)` +
                (out[0] ? `; nearest ${out[0].zip} @ ${out[0].mi}mi` : '')
            );
            return out;
        }

        async function routingListByIds(tableId, ids, fields) {
            const uniq = [...new Set((ids || []).filter((id) => typeof id === 'string' && id.startsWith('rec')))];
            const all = [];
            const chunk = 20;
            for (let i = 0; i < uniq.length; i += chunk) {
                const slice = uniq.slice(i, i + chunk);
                if (!slice.length) continue;
                const formula = `OR(${slice.map((id) => `RECORD_ID()="${id}"`).join(',')})`;
                try {
                    const batch = await airtableFetchAllRecords(tableId, {
                        formula,
                        fields: fields && fields.length ? fields : undefined,
                    });
                    all.push(...batch);
                } catch (e) {
                    console.warn('routingListByIds batch failed', tableId, e);
                }
            }
            return all;
        }

        async function routingBuildExpandedRows(neighbors, homeZip, traceStep) {
            if (!neighbors.length) return [];
            await zipRouteEnsureInfrastructure();
            const t0 = Date.now();
            const withRec = neighbors.filter((n) => n.rec);
            const needLookup = neighbors.filter((n) => !n.rec);
            const meta = new Map(); // zipRecId -> neighbor
            for (const n of withRec) meta.set(n.rec, n);

            // Resolve missing rec ids via US Zips table
            for (const n of needLookup) {
                try {
                    const rid = await zipRouteFindZipRecordId(n.zip);
                    if (rid) {
                        n.rec = rid;
                        meta.set(rid, n);
                    }
                } catch (_) {}
            }

            const zipRecs = neighbors.map((n) => n.rec).filter(Boolean);
            if (!zipRecs.length) {
                traceStep('[Expanded] no US Zip record ids for neighbors');
                return [];
            }

            const zipRows = await routingListByIds(ZIP_ROUTE.US_ZIPS_TABLE, zipRecs, ['Zip', 'Adset Zip Tracking']);
            const zipById = new Map(zipRows.map((r) => [r.id, r]));
            const juncIds = [];
            for (const zrec of zipRecs) {
                const zrow = zipById.get(zrec);
                const links = zrow && zrow.fields ? zrow.fields['Adset Zip Tracking'] : null;
                if (Array.isArray(links)) {
                    for (const jid of links) {
                        if (typeof jid === 'string' && jid.startsWith('rec')) juncIds.push(jid);
                    }
                }
            }
            const uniqJ = [...new Set(juncIds)];
            traceStep(`[Expanded] neighbor zips=${zipRecs.length} → junction ids=${uniqJ.length}`);

            let juncRecs = [];
            if (uniqJ.length) {
                juncRecs = await routingListByIds(
                    ZIP_ROUTE.ADSET_ZIPS_TABLE,
                    uniqJ,
                    [ZIP_ROUTE.JUNCTION_ADSET_FIELD, 'US Zips', 'Linked at']
                );
            }

            const neighborSet = new Set(zipRecs);
            const rows = [];
            for (const rec of juncRecs) {
                const zlinks = rec.fields && rec.fields['US Zips'];
                const zarr = Array.isArray(zlinks) ? zlinks : (zlinks ? [zlinks] : []);
                const matched = zarr.filter((z) => neighborSet.has(z));
                if (!matched.length) continue;
                const ads = zipRouteAdsetIdsFromJunctionFields(rec.fields || {});
                for (const zrec of matched) {
                    const n = meta.get(zrec) || {};
                    for (const aid of ads) {
                        const clientRec = zipRouteFindClientRecordForAdset(aid);
                        const adsetRec = zipRouteAdsetById ? zipRouteAdsetById.get(aid) : null;
                        rows.push({
                            junctionId: rec.id,
                            linkCreated: (rec.fields && rec.fields['Linked at']) || rec.createdTime,
                            adsetId: aid,
                            clientRec,
                            adsetRec,
                            matchedZip: n.zip || null,
                            matchedZipRec: zrec,
                            distanceMi: n.mi == null ? null : Number(n.mi),
                            homeZip,
                        });
                    }
                }
            }
            rows.sort((a, b) => {
                const da = a.distanceMi == null ? 9999 : a.distanceMi;
                const db = b.distanceMi == null ? 9999 : b.distanceMi;
                if (da !== db) return da - db;
                return String(a.linkCreated || '').localeCompare(String(b.linkCreated || ''));
            });
            traceStep(`[Expanded] candidate rows=${rows.length} in ${((Date.now() - t0) / 1000).toFixed(2)}s`);
            return rows;
        }

        function parseRevenueFloor(raw) {
            const s0 = String(raw || '').trim();
            if (!s0) return null;
            const s = s0.toLowerCase().replace(/,/g, '').replace(/\$/g, '').replace(/\s+/g, ' ');
            if (s.includes('less than') || s.startsWith('less-than') || s.includes('under')) return 0;
            const slug = s.match(/(less-than|more-than)?\s*(\d+)\s*k(?:\s*-\s*(\d+)\s*k)?/);
            if (slug) {
                const kind = slug[1] || '';
                const a = Number(slug[2]) * 1000;
                if (kind === 'less-than') return 0;
                if (kind === 'more-than') return a;
                return a;
            }
            if (s.includes('more than') || s.startsWith('more-than')) {
                const n = Number((s.match(/(\d{2,})/) || [])[1] || NaN);
                if (Number.isFinite(n)) return n < 1000 ? n * 1000 : n;
            }
            const nums = [...s.matchAll(/(\d+(?:\.\d+)?)\s*(k)?/g)].map((m) => {
                const n = Number(m[1]);
                return m[2] ? n * 1000 : n;
            }).filter((n) => Number.isFinite(n));
            if (!nums.length) return null;
            return Math.min(...nums);
        }

        function revenueQualifies100k(raw) {
            const floor = parseRevenueFloor(raw);
            return floor != null && floor >= 100000;
        }

        function b2bNicheMatches(niches, funnelNiche) {
            const key = String(funnelNiche || '').trim().toLowerCase();
            const aliases = B2B_NICHE_ALIASES[key] || [key];
            const have = (Array.isArray(niches) ? niches : [niches]).map((x) => String(x || '').trim().toLowerCase());
            return have.some((h) => aliases.some((a) => h === a || h.includes(a) || a.includes(h)));
        }

        function extractB2bZip(fields) {
            const loc = String((fields && fields.Location) || '').trim();
            if (loc) {
                const pure = loc.match(/^(\d{5})(?:-\d{4})?$/);
                if (pure) return { zip: pure[1], source: 'Location' };
                const embedded = loc.match(/\b(\d{5})(?:-\d{4})?\b/);
                if (embedded) return { zip: embedded[1], source: 'Location-embedded' };
            }
            const notes = String((fields && fields.Notes) || '');
            const fromNotes =
                notes.match(/Zip\s*Code\s*:\s*(\d{5})\b/i) ||
                notes.match(/\bZIP\b\s*[:=]?\s*(\d{5})\b/i);
            if (fromNotes) return { zip: fromNotes[1], source: 'Notes' };
            return null;
        }

        function pickRandom(arr) {
            if (!arr || !arr.length) return null;
            return arr[Math.floor(Math.random() * arr.length)];
        }

        async function loadQualifiedB2bPool(traceStep) {
            if (b2bPoolCache && b2bPoolCache.byZip) {
                traceStep(
                    `[B2B] using cached pool qualified=${b2bPoolCache.qualifiedCount} zips=${b2bPoolCache.byZip.size}`
                );
                return b2bPoolCache;
            }
            const t0 = Date.now();
            const formulaParts = [
                'NOT({Status}="Disqualified")',
                'OR({Discovery Status}="", {Discovery Status}=BLANK(), NOT({Discovery Status}="Close Won"))',
                'AND({Contact Email}!="", {Contact Email}!=BLANK())',
                'OR(AND({Phone Number}!="", {Phone Number}!=BLANK()), AND({Parsed Phone}!="", {Parsed Phone}!=BLANK()))',
                `IS_AFTER(CREATED_TIME(), "${B2B_CREATED_AFTER}")`,
            ];
            const filter = `AND(${formulaParts.join(',')})`;
            const fields = [
                'Business Name', 'Status', 'Discovery Status', 'Estimated monthly revenue',
                'Niche(s)', 'Contact Email', 'Phone Number', 'Parsed Phone', 'Created',
                'Location', 'Notes',
            ];
            const pool = [];
            let offset = null;
            let pages = 0;
            do {
                const u = new URL(`${AIRTABLE_BASE_URL}/${B2B_TABLE_ID}`, window.location.origin);
                u.searchParams.set('pageSize', '100');
                u.searchParams.set('filterByFormula', filter);
                for (const f of fields) u.searchParams.append('fields[]', f);
                if (offset) u.searchParams.set('offset', offset);
                const page = await fetchAirtableData(u.toString());
                pool.push(...(page.records || []));
                offset = page.offset || null;
                pages += 1;
                if (pages >= 15) break;
                if (offset) await sleepZipRoute(120);
            } while (offset);

            const byZip = new Map();
            let qualified = 0;
            let noZip = 0;
            for (const rec of pool) {
                const f = rec.fields || {};
                if (f.Status === 'Disqualified') continue;
                if (f['Discovery Status'] === 'Close Won') continue;
                const email = String(f['Contact Email'] || '').trim();
                const phone = String(f['Phone Number'] || f['Parsed Phone'] || '').trim();
                if (!email || !phone) continue;
                if (!b2bNicheMatches(f['Niche(s)'], FUNNEL_ADSET_NICHE)) continue;
                if (!revenueQualifies100k(f['Estimated monthly revenue'])) continue;
                const created = rec.createdTime || f.Created;
                if (!created || Date.parse(created) < Date.parse(B2B_CREATED_AFTER)) continue;
                qualified += 1;
                const zinfo = extractB2bZip(f);
                if (!zinfo) {
                    noZip += 1;
                    continue;
                }
                if (!byZip.has(zinfo.zip)) byZip.set(zinfo.zip, []);
                byZip.get(zinfo.zip).push({ rec, zipSource: zinfo.source, leadZip: zinfo.zip });
            }
            b2bPoolCache = {
                byZip,
                qualifiedCount: qualified,
                fetched: pool.length,
                pages,
                noZip,
                loadedAt: Date.now(),
            };
            traceStep(
                `[B2B] pool fetched=${pool.length} pages=${pages} qualified=${qualified} ` +
                `withZip=${qualified - noZip} noZip=${noZip} distinctZips=${byZip.size} ` +
                `(${((Date.now() - t0) / 1000).toFixed(2)}s)`
            );
            return b2bPoolCache;
        }

        async function pickB2BOverflow(homeZip, traceStep) {
            const t0 = Date.now();
            const pool = await loadQualifiedB2bPool(traceStep);
            const byZip = pool.byZip;

            traceStep(`[B2B 3a] exact Location ZIP = ${homeZip}`);
            const exactHits = byZip.get(homeZip) || [];
            traceStep(`[B2B 3a] exact hits: ${exactHits.length}`);
            exactHits.slice(0, 8).forEach((h, i) => {
                const f = h.rec.fields || {};
                traceStep(
                    `  exactB2B[${i + 1}] ${f['Business Name'] || h.rec.id} | loc=${f.Location || '—'} | src=${h.zipSource}`
                );
            });
            if (exactHits.length) {
                const hit = pickRandom(exactHits);
                const f = hit.rec.fields || {};
                traceStep(
                    `[B2B 3a] random among ${exactHits.length}: ${f['Business Name'] || hit.rec.id} ` +
                    `(${((Date.now() - t0) / 1000).toFixed(2)}s)`
                );
                return {
                    matchMode: 'exact',
                    matchedZip: homeZip,
                    distanceMi: 0,
                    leadZip: hit.leadZip,
                    zipSource: hit.zipSource,
                    poolSize: exactHits.length,
                    rec: hit.rec,
                };
            }

            traceStep('[B2B 3b] CDN neighbor ZIPs (30mi / top 25, closest first)');
            const neighbors = await routingLoadNeighbors(homeZip, traceStep);
            if (!neighbors.length) {
                traceStep('[B2B 3b] no CDN neighbors — no B2B geo match');
                return null;
            }
            let scanned = 0;
            let bucket = [];
            let firstDist = null;
            for (const n of neighbors) {
                scanned += 1;
                const hits = byZip.get(n.zip) || [];
                if (!hits.length) continue;
                firstDist = n.mi;
                bucket = hits.map((h) => ({ ...h, matchedZip: n.zip, distanceMi: n.mi }));
                break;
            }
            traceStep(
                `[B2B 3b] scannedUntilHit=${scanned}/${neighbors.length} ` +
                `closestHitZip=${bucket[0] ? bucket[0].matchedZip : '—'} @ ${firstDist != null ? firstDist : '—'}mi ` +
                `candidates=${bucket.length}`
            );
            if (!bucket.length) {
                traceStep('[B2B 3b] no B2B on neighbor ZIPs — no national random fallback');
                return null;
            }
            const hit = pickRandom(bucket);
            const f = hit.rec.fields || {};
            traceStep(
                `[B2B 3b] random among ${bucket.length} on ${hit.matchedZip}: ` +
                `${f['Business Name'] || hit.rec.id} @ ${hit.distanceMi}mi (${((Date.now() - t0) / 1000).toFixed(2)}s)`
            );
            return {
                matchMode: 'expanded',
                matchedZip: hit.matchedZip,
                distanceMi: hit.distanceMi,
                leadZip: hit.leadZip,
                zipSource: hit.zipSource,
                poolSize: bucket.length,
                rec: hit.rec,
            };
        }

        function emptyRoute(message) {
            return {
                phase: 4,
                tier: null,
                selected: null,
                b2b: null,
                phase1Rows: [],
                expandedRows: [],
                message: message || 'No match',
                matchType: 'None',
            };
        }

        /** Exact → CDN expanded → B2B exact → B2B CDN. */
        async function computeLeadRoute(zipInput) {
            const zipFive = zipRouteNormalizeZipFive(zipInput);
            const empty = emptyRoute('No match');
            const trace = [];
            const traceStep = (msg) => trace.push(msg);
            lastLeadRoutePick = empty;
            lastZipRoutingQueue = [];
            lastClientSearchTrace = trace;
            traceStep(`[S1] DRY-RUN bathrooms router rawZip="${String(zipInput || '')}" normalizedZip="${zipFive}"`);
            traceStep('[S1b] rules: Active-only; no capacity; exact→CDN expanded→B2B exact→B2B CDN; no national B2B random');
            if (!/^\d{5}$/.test(zipFive)) {
                traceStep('[S2] zip validation failed');
                lastLeadRoutePick = emptyRoute('Invalid zip');
                return lastLeadRoutePick;
            }
            try {
                traceStep('[S2] zip validation passed');
                await zipRouteEnsureInfrastructure();
                traceStep(
                    `[S3] infra clients=${Array.isArray(zipRouteClientsCache) ? zipRouteClientsCache.length : 0} ` +
                    `adsets=${zipRouteAdsetById ? zipRouteAdsetById.size : 0}`
                );

                // Phase 1 exact
                traceStep('[P1] exact Adset Zip Tracking');
                const phase1Rows = await zipRouteBuildPhase1Rows(zipFive);
                lastZipRoutingQueue = phase1Rows;
                phase1Rows.forEach((row, idx) => {
                    const af = row.adsetRec && row.adsetRec.fields;
                    const clientName = row.clientRec && row.clientRec.fields
                        ? String(row.clientRec.fields.Name || '').trim() : '';
                    const adsetName = af && af['Adset Name'] ? String(af['Adset Name']).trim() : '';
                    const tier = af ? routingComputeTier(row.clientRec, af) : 0;
                    traceStep(
                        `[P1.${idx + 1}] ${tier >= 1 ? 'ELIGIBLE' : 'skip'} j=${row.junctionId || '—'} ` +
                        `adset=${row.adsetId || '—'} "${adsetName}" client="${clientName}" ` +
                        `clientActive=${routingBoolLabel(af ? routingIsClientActive(row.clientRec, af) : false)} ` +
                        `adsetActive=${routingBoolLabel(af ? routingIsAdsetActive(af) : false)} linked=${row.linkCreated || '—'}`
                    );
                });
                const pick1 = routingPickPartnerFromPool(routingDedupeCandidatesByAdset(phase1Rows));
                if (pick1) {
                    const name = pick1.clientRec && pick1.clientRec.fields
                        ? String(pick1.clientRec.fields.Name || '').trim() : '';
                    traceStep(`[P1] SELECT exact client="${name}" adset=${pick1.adsetId} junction=${pick1.junctionId}`);
                    lastLeadRoutePick = {
                        phase: 1,
                        tier: 1,
                        selected: pick1,
                        b2b: null,
                        phase1Rows,
                        expandedRows: [],
                        message: `Exact zip match — ${name || pick1.adsetId}`,
                        matchType: 'Exact',
                    };
                    return lastLeadRoutePick;
                }
                traceStep('[P1] no eligible exact Active partner');

                // Phase 2 expanded via CDN
                traceStep('[P2] CDN expanded Adset Zip Tracking (30mi / top 25)');
                const neighbors = await routingLoadNeighbors(zipFive, traceStep);
                const expandedRows = await routingBuildExpandedRows(neighbors, zipFive, traceStep);
                let shown = 0;
                for (const row of expandedRows) {
                    const af = row.adsetRec && row.adsetRec.fields;
                    if (!af || routingComputeTier(row.clientRec, af) < 1) continue;
                    const clientName = row.clientRec && row.clientRec.fields
                        ? String(row.clientRec.fields.Name || '').trim() : '';
                    const adsetName = af['Adset Name'] ? String(af['Adset Name']).trim() : '';
                    traceStep(
                        `[P2.elig] ${clientName || '?'} / ${adsetName || row.adsetId} via ${row.matchedZip} @ ${row.distanceMi}mi`
                    );
                    shown += 1;
                    if (shown >= 10) break;
                }
                const pick2 = routingPickClosestThenOldest(expandedRows);
                if (pick2) {
                    const name = pick2.clientRec && pick2.clientRec.fields
                        ? String(pick2.clientRec.fields.Name || '').trim() : '';
                    traceStep(
                        `[P2] SELECT expanded client="${name}" adset=${pick2.adsetId} ` +
                        `via ${pick2.matchedZip} @ ${pick2.distanceMi}mi junction=${pick2.junctionId}`
                    );
                    lastLeadRoutePick = {
                        phase: 2,
                        tier: 1,
                        selected: pick2,
                        b2b: null,
                        phase1Rows,
                        expandedRows,
                        message: `Expanded zip match via ${pick2.matchedZip} @ ${pick2.distanceMi}mi — ${name || pick2.adsetId}`,
                        matchType: 'Expanded',
                    };
                    return lastLeadRoutePick;
                }
                traceStep('[P2] no eligible expanded Active partner');

                // Phase 3 B2B geo
                traceStep('[P3] B2B overflow geo-aware');
                const b2b = await pickB2BOverflow(zipFive, traceStep);
                if (b2b && b2b.rec) {
                    const f = b2b.rec.fields || {};
                    const biz = String(f['Business Name'] || b2b.rec.id).trim();
                    traceStep(
                        `[P3] SELECT B2B ${b2b.matchMode} "${biz}" zip=${b2b.matchedZip}` +
                        (b2b.distanceMi != null ? ` @ ${b2b.distanceMi}mi` : '')
                    );
                    // Synthesize a client-like object so thank-you UI can show a name.
                    const syntheticClient = {
                        // Never use a real B2B table id here — hydrateClientReviewsByIdIfNeeded
                        // would GET Clients/{id} and overwrite Name with the wrong record (or empty).
                        id: 'b2b:' + String(b2b.rec.id),
                        createdTime: b2b.rec.createdTime,
                        isB2B: true,
                        fields: {
                            Name: biz,
                            Status: 'Active',
                            'Lead Price': null,
                            'Submit Screen': 'None',
                            __b2bDryRun: true,
                            __b2bRecordId: b2b.rec.id,
                            __b2bMatchMode: b2b.matchMode,
                            __b2bMatchedZip: b2b.matchedZip,
                            __b2bDistanceMi: b2b.distanceMi,
                        },
                    };
                    const syntheticSelected = {
                        tier: null,
                        adsetId: null,
                        clientRec: syntheticClient,
                        adsetRec: null,
                        junctionId: null,
                        linkCreated: null,
                        matchedZip: b2b.matchedZip,
                        distanceMi: b2b.distanceMi,
                        b2bId: b2b.rec.id,
                        isB2B: true,
                    };
                    lastLeadRoutePick = {
                        phase: 3,
                        tier: null,
                        selected: syntheticSelected,
                        b2b: {
                            id: b2b.rec.id,
                            businessName: biz,
                            matchMode: b2b.matchMode,
                            matchedZip: b2b.matchedZip,
                            distanceMi: b2b.distanceMi,
                            leadZip: b2b.leadZip,
                            zipSource: b2b.zipSource,
                            poolSize: b2b.poolSize,
                            revenue: f['Estimated monthly revenue'] || null,
                            niches: f['Niche(s)'] || [],
                            location: f.Location || null,
                            email: f['Contact Email'] || null,
                            phone: f['Phone Number'] || f['Parsed Phone'] || null,
                        },
                        phase1Rows,
                        expandedRows,
                        message:
                            b2b.matchMode === 'exact'
                                ? `B2B exact Location ZIP — ${biz}`
                                : `B2B expanded via ${b2b.matchedZip} @ ${b2b.distanceMi}mi — ${biz}`,
                        matchType: b2b.matchMode === 'exact' ? 'B2B Exact' : 'B2B Expanded',
                    };
                    return lastLeadRoutePick;
                }

                traceStep('[P4] no B2C partner and no B2B geo match');
                lastLeadRoutePick = {
                    ...emptyRoute('No qualifying partner or B2B geo match'),
                    phase1Rows,
                    expandedRows,
                };
                return lastLeadRoutePick;
            } catch (e) {
                console.error('computeLeadRoute failed:', e);
                traceStep(`[SERR] computeLeadRoute exception: ${String(e && e.message ? e.message : e)}`);
                lastLeadRoutePick = emptyRoute(e.message || String(e));
                lastZipRoutingQueue = [];
                return lastLeadRoutePick;
            }
        }
'''


def replace_function_block(src: str, start_pat: str, end_before_pat: str, new_block: str) -> str:
    start = re.search(start_pat, src)
    if not start:
        raise SystemExit(f"start not found: {start_pat}")
    end = re.search(end_before_pat, src[start.start():])
    if not end:
        raise SystemExit(f"end not found: {end_before_pat}")
    abs_end = start.start() + end.start()
    return src[: start.start()] + new_block + src[abs_end:]


def main() -> None:
    src = SRC.read_text()

    # 1) Head hardening
    if "<base " not in src:
        src = src.replace("<head>", "<head>\n" + HEAD_INJECT, 1)
    else:
        src = src.replace("<head>", "<head>\n" + HEAD_INJECT, 1)

    # robots if missing after inject is fine
    # Kill live Meta pixel loader block by wrapping — simplest: insert boot script right after <head> inject
    src = src.replace("<head>\n" + HEAD_INJECT, "<head>\n" + HEAD_INJECT + "\n" + BOOT_SCRIPT, 1)

    # Title
    src = src.replace(
        "<title>Find Your Local Pick - Bathroom Remodel</title>",
        "<title>DRY-RUN Bathrooms (no Airtable writes)</title>",
        1,
    )

    # Banner after <body>
    src = re.sub(r"<body([^>]*)>", r"<body\1>\n" + BANNER_HTML, src, count=1)

    # TESTING_MODE hard true
    src = re.sub(
        r"const TESTING_MODE = false; // Production: Airtable writes \+ Meta enabled",
        "const TESTING_MODE = true; // DRY-RUN: hard-locked no Airtable writes / no Meta",
        src,
        count=1,
    )

    # Force verbose debug
    src = re.sub(
        r"const TLP_DEBUG_VERBOSE = window\.TLP_DEBUG_VERBOSE === true;",
        "const TLP_DEBUG_VERBOSE = true;",
        src,
        count=1,
    )

    # Use GET-only proxy base (also rewritten by fetch guard)
    src = src.replace(
        "const AIRTABLE_BASE_URL = `/api/airtable/v0/${AIRTABLE_BASE_ID}`;",
        "const AIRTABLE_BASE_URL = `/api/airtable-readonly/v0/${AIRTABLE_BASE_ID}`;",
        1,
    )

    # Insert panel helper near tlpDebug
    src = src.replace(
        "function tlpDebug(scope, message, details) {",
        PANEL_HELPER + "\n        function tlpDebug(scope, message, details) {",
        1,
    )

    # Replace capacity+computeLeadRoute section
    src = replace_function_block(
        src,
        r"        function routingWeeklyRemaining\(adsetFields\) \{",
        r"\n        function isLikelyIpAddress\(",
        NEW_ROUTING + "\n",  # keep original isLikelyIpAddress(...) that follows
    )

    # Upgrade buildClientSearchLog to include B2B / matchType / dry-run notice
    old_log_return = "            return lines.join('\\n');\n        }\n\n        function normalizeMetaPixelId"
    new_log_fn_tail = r'''
            if (route.matchType) {
                lines.push(`Match Type: ${route.matchType}`);
            }
            if (route.b2b) {
                const b = route.b2b;
                lines.push('', 'B2B Would-Link:');
                lines.push(`B2B Business: ${b.businessName || 'none'}`);
                lines.push(`B2B Record ID: ${b.id || 'none'}`);
                lines.push(`B2B Mode: ${b.matchMode || 'none'}`);
                lines.push(`B2B Matched Zip: ${b.matchedZip || 'none'}`);
                lines.push(`B2B Distance Mi: ${b.distanceMi != null ? b.distanceMi : 'n/a'}`);
                lines.push(`B2B Location: ${b.location || 'none'}`);
                lines.push(`B2B Revenue: ${b.revenue || 'none'}`);
                lines.push(`B2B Pool Size: ${b.poolSize != null ? b.poolSize : 'n/a'}`);
            }
            lines.push('', 'DRY-RUN: no Airtable writes. Caps not applied in matcher. Meta pixel off.');
            lines.push(`Write blocks this session: ${window.__TLP_DRY_RUN_WRITE_BLOCKS__ || 0}`);
            return lines.join('\n');
        }

        function normalizeMetaPixelId'''
    if old_log_return not in src:
        raise SystemExit("buildClientSearchLog tail not found")
    src = src.replace(old_log_return, new_log_fn_tail, 1)

    # After routing completes in submitFinalForm, show dry-run panel.
    # Hook just after getClientForZipUsingPrefetch assignment block.
    needle = "                matchedClientData = await getClientForZipUsingPrefetch(finalData.address.zip);\n                genericLeadFlow = !matchedClientData;"
    inject = needle + """
                try {
                    const logText = buildClientSearchLog(
                        finalData.address && finalData.address.zip,
                        routingErrorText,
                        !!(lastLeadRoutePick && lastLeadRoutePick.selected && lastLeadRoutePick.selected.adsetId),
                        { dryRun: 'yes', writeBlocks: window.__TLP_DRY_RUN_WRITE_BLOCKS__ || 0 }
                    );
                    tlpShowDryRunLog(logText);
                } catch (e) {
                    console.warn('dry-run log panel failed', e);
                }
"""
    if needle not in src:
        raise SystemExit("submitFinalForm routing needle not found")
    src = src.replace(needle, inject, 1)

    # Also show log when patch path builds log (even if no lead id) — after final showConfirmation paths is hard;
    # add another show after adset diagnostics patch try completes.
    needle2 = "            if (adsetLinked && adsetRecordId) {\n                const routedAdsetForPixel = getRoutedAdsetFields();\n                fireDynamicMetaLead(routedAdsetForPixel, leadEventData, eventId);\n            }"
    inject2 = """            try {
                const logText2 = buildClientSearchLog(
                    finalData.address && finalData.address.zip,
                    routingErrorText,
                    adsetLinked,
                    adsetLinkDiagnostics
                );
                tlpShowDryRunLog(logText2);
            } catch (e) {}

            if (adsetLinked && adsetRecordId) {
                const routedAdsetForPixel = getRoutedAdsetFields();
                fireDynamicMetaLead(routedAdsetForPixel, leadEventData, eventId);
            }"""
    if needle2 not in src:
        raise SystemExit("pixel needle not found")
    src = src.replace(needle2, inject2, 1)

    # Safety: ensure submitLeadToAirtable still short-circuits (already does on TESTING_MODE)
    if "if (TESTING_MODE) {\n                console.log('[TESTING_MODE] Airtable writes and duplicate checks skipped" not in src:
        raise SystemExit("submitLeadToAirtable TESTING_MODE guard missing")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(src)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes, {src.count(chr(10))+1} lines)")


if __name__ == "__main__":
    main()
