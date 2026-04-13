#!/usr/bin/env node
/**
 * Prints Airtable base schema for wiring bathrooms funnel fields.
 *
 * Do NOT paste your token into this file or into chat. Rotate tokens if exposed.
 *
 * Mode A — Metadata API (field names + types + select options):
 *   Token needs scope: schema.bases:read for this base.
 *
 * Mode B — Data API fallback (field names only, from sample records):
 *   Runs automatically if metadata returns 403, or pass --records-only
 *   Token needs: data.records:read for this base.
 *
 * PowerShell:
 *   $env:AIRTABLE_TOKEN = "pat_...."
 *   $env:AIRTABLE_BASE_ID = "appmBb0lzqRK9dI8v"
 *   node scripts/dump-airtable-schema.mjs
 *   node scripts/dump-airtable-schema.mjs --records-only
 */

const BASE_ID = process.env.AIRTABLE_BASE_ID || 'appmBb0lzqRK9dI8v';
const TOKEN = process.env.AIRTABLE_TOKEN || process.env.AIRTABLE_API_KEY;
const RECORDS_ONLY = process.argv.includes('--records-only');

/** Table IDs referenced by testing/bathrooms.html (deduped). */
const KNOWN_TABLES = [
    { id: 'tblH2nVfmGNG8pAjC', label: 'Clients (ZIP_ROUTE / junction)' },
    { id: 'tblee61crNCoSfurx', label: 'Adset' },
    { id: 'tbl87JqHAdJwgq1GL', label: 'Adset Zips junction' },
    { id: 'tblieaHIf6rDfFZFl', label: 'US Zips' },
    { id: 'tbl6uhtOFzGzA7EMu', label: 'Campaigns' },
    { id: 'tblPt6Wc79hTBSmcD', label: 'B2C Leads' },
    { id: 'tbl7ungQGMMLYwshw', label: 'B2C Ads' },
    { id: 'tbl5JDBRhTzuxzsc4', label: 'URL Parameters' },
];

function summarizeOptions(field) {
    const o = field.options;
    if (!o || typeof o !== 'object') return undefined;
    if (field.type === 'singleSelect' || field.type === 'multipleSelects') {
        return (o.choices || []).map((c) => c.name);
    }
    if (field.type === 'multipleRecordLinks' || field.type === 'singleRecordLink') {
        return { linkedTableId: o.linkedTableId };
    }
    return Object.keys(o).length ? o : undefined;
}

function sampleValueType(v) {
    if (v === null || v === undefined) return 'empty';
    if (Array.isArray(v)) {
        if (v.length === 0) return 'array[]';
        const first = v[0];
        if (typeof first === 'string' && first.startsWith('rec')) return 'array[recordId]';
        if (typeof first === 'object' && first && 'url' in first) return 'array[attachment]';
        return `array[${typeof first}]`;
    }
    return typeof v;
}

async function fetchMetadata() {
    const url = `https://api.airtable.com/v0/meta/bases/${BASE_ID}/tables`;
    const res = await fetch(url, {
        headers: { Authorization: `Bearer ${TOKEN}` },
    });
    const text = await res.text();
    return { ok: res.ok, status: res.status, statusText: res.statusText, text };
}

async function inferFieldsFromRecords(tableId, label) {
    const url = `https://api.airtable.com/v0/${BASE_ID}/${encodeURIComponent(tableId)}?maxRecords=5`;
    const res = await fetch(url, {
        headers: { Authorization: `Bearer ${TOKEN}` },
    });
    const text = await res.text();
    let data;
    try {
        data = JSON.parse(text);
    } catch {
        return {
            id: tableId,
            label,
            error: 'invalid_json',
            httpStatus: res.status,
            bodyPreview: text.slice(0, 200),
        };
    }
    if (!res.ok) {
        return {
            id: tableId,
            label,
            error: data.error || res.statusText,
            httpStatus: res.status,
            message: data.error?.message || text.slice(0, 300),
        };
    }
    const records = data.records || [];
    const keySet = new Set();
    const sampleByField = {};
    for (const rec of records) {
        const f = rec.fields || {};
        for (const k of Object.keys(f)) {
            keySet.add(k);
            if (sampleByField[k] === undefined && f[k] !== undefined && f[k] !== null && f[k] !== '') {
                sampleByField[k] = f[k];
            }
        }
    }
    const fieldNames = [...keySet].sort();
    return {
        id: tableId,
        label,
        source: 'data_api_sample',
        note: 'Types inferred from up to 5 records; empty columns will be missing.',
        recordCountSampled: records.length,
        fields: fieldNames.map((name) => ({
            name,
            inferredValueType: sampleValueType(sampleByField[name]),
        })),
    };
}

async function dumpFromRecords() {
    const results = [];
    for (const t of KNOWN_TABLES) {
        results.push(await inferFieldsFromRecords(t.id, t.label));
    }
    const out = {
        baseId: BASE_ID,
        source: 'data_api',
        tables: results,
    };
    console.log(JSON.stringify(out, null, 2));
}

async function main() {
    if (!TOKEN) {
        console.error('Missing AIRTABLE_TOKEN (or AIRTABLE_API_KEY). See header comment in this file.');
        process.exitCode = 1;
        return;
    }

    if (RECORDS_ONLY) {
        await dumpFromRecords();
        return;
    }

    const meta = await fetchMetadata();
    if (!meta.ok) {
        console.error('Airtable metadata request failed:', meta.status, meta.statusText);
        console.error(meta.text);
        if (meta.status === 403 || meta.status === 404) {
            console.error(
                '\n--- Fallback: inferring field NAMES from sample records (data.records:read) ---\n'
            );
            await dumpFromRecords();
            console.error(
                '\n(Optional) For full types + all tables: edit your PAT at airtable.com/create/tokens — add scope "schema.bases:read" and access to this base, then run again without --records-only.'
            );
            return;
        }
        process.exitCode = 1;
        return;
    }

    let data;
    try {
        data = JSON.parse(meta.text);
    } catch {
        console.error('Invalid JSON from Airtable metadata');
        process.exitCode = 1;
        return;
    }

    const tables = data.tables || [];
    const out = tables.map((t) => ({
        id: t.id,
        name: t.name,
        fields: (t.fields || []).map((f) => {
            const row = { name: f.name, type: f.type };
            const opt = summarizeOptions(f);
            if (opt !== undefined) row.options = opt;
            return row;
        }),
    }));

    console.log(JSON.stringify({ baseId: BASE_ID, source: 'metadata_api', tables: out }, null, 2));
}

main().catch((e) => {
    console.error(e);
    process.exitCode = 1;
});
