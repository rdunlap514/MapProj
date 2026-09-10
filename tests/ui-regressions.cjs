const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const source = name => fs.readFileSync(path.join(root, 'templates', name + '.html'), 'utf8');
function between(s, start, end) { return s.slice(s.indexOf(start), s.indexOf(end, s.indexOf(start))); }
(async () => {
    for (const name of ['admin', 'user']) {
        const script = source(name).match(/<script>([\s\S]*?)<\/script>/)[1].replace(/\{\{.*?\}\}/g, 'false');
        new vm.Script(script);
    }
    const browser = await chromium.launch({headless: true, channel: process.env.MAPPROJ_BROWSER_CHANNEL || undefined});
    try {
        const page = await browser.newPage();
        // Exercise the real shared wrapper: tokens go on writes, never to other origins.
        await page.route('https://mapproj.test/**', route => route.fulfill({body: '<html></html>', contentType: 'text/html'}));
        await page.goto('https://mapproj.test/');
        const securityScript = source('_security').match(/<script>([\s\S]*?)<\/script>/)[1].replace(/\{\{.*?\}\}/g, '"test-token"');
        const sent = await page.evaluate(async script => {
            const sent = [];
            window.fetch = async (input, options = {}) => { sent.push({url: String(input), token: new Headers(options.headers).get('X-CSRF-Token')}); };
            eval(script);
            await window.fetch('/api/login', {method: 'POST'});
            await window.fetch('/api/buildings');
            await window.fetch('https://elsewhere.test/', {method: 'POST'});
            return sent;
        }, securityScript);
        assert.deepEqual(sent.map(item => item.token), ['test-token', null, null]);
        for (const name of ['admin', 'user']) {
            await page.setContent('<div id="notesSection"></div><div id="notesDisplay"></div>');
            const s = source(name);
            const fn = name === 'admin' ? between(s, 'async function loadAdminNotes(', 'async function resolveNote(') : between(s, 'async function loadNotesForRoom(', 'async function submitNote(');
            // Extract the helper alone, without unrelated top-level initialization.
            const helper = s.match(/function escapeHtml\(value\) \{[\s\S]*?\n        \}/)[0];
            const result = await page.evaluate(async ({helper, fn, name}) => {
                const payload = '<img src=x onerror="window.injected=true">';
                const currentBuilding = 'Demo';
                const roomId = "101');window.injected=true;//";
                const fetch = async () => ({json: async () => ({[roomId]: [{author: payload, text: payload, timestamp: '2026-01-01'}]})});
                let resolved = null;
                const resolveNote = id => { resolved = id; };
                const deleteNote = () => {};
                await eval(helper + '\n' + fn + '\n' + (name === 'admin' ? 'loadAdminNotes' : 'loadNotesForRoom') + '(roomId)');
                document.querySelector('[data-resolve-note]')?.click();
                return {images: document.querySelectorAll('img').length, text: document.body.textContent, injected: !!window.injected, resolved, roomId};
            }, {helper, fn, name});
            assert.equal(result.images, 0);
            assert.equal(result.injected, false);
            assert.ok(result.text.includes('<img src=x'));
            if (name === 'admin') assert.equal(result.resolved, result.roomId);
        }
        const saveFn = between(source('user'), 'async function saveRoomChange(', 'async function setColorFromPopover(');
        for (const scenario of ['viewer', 'forbidden', 'redirect', 'network', 'success']) {
            const result = await page.evaluate(async ({saveFn, scenario}) => {
                const canEdit = scenario !== 'viewer';
                let savingRoom = false, currentBuilding = 'Demo', colorPopoverRoom = '101';
                let roomBounds = {'101': {color: 'red'}};
                let requests = 0, alerts = 0, redraws = 0;
                const alert = () => alerts++;
                const redraw = () => redraws++;
                const fetch = async (url, options) => {
                    if (!url.endsWith('/status') || JSON.stringify(JSON.parse(options.body)) !== JSON.stringify({room_id: '101', changes: {color: 'green'}})) throw new Error('Wrong status request');
                    requests++;
                    if (scenario === 'network') throw new Error('Network failure');
                    return {ok: scenario !== 'forbidden', redirected: scenario === 'redirect', json: async () => ({success: true})};
                };
                await eval(saveFn + '\nsaveRoomChange({color: "green"})');
                return {color: roomBounds['101'].color, requests, alerts, redraws};
            }, {saveFn, scenario});
            assert.equal(result.color, scenario === 'success' ? 'green' : 'red');
            assert.equal(result.requests, scenario === 'viewer' ? 0 : 1);
            assert.equal(result.alerts, ['forbidden', 'redirect', 'network'].includes(scenario) ? 1 : 0);
            assert.equal(result.redraws, scenario === 'success' ? 1 : 0);
        }
        console.log('PASS: template JavaScript syntax, safe note rendering, note actions, viewer guard, rejected/redirected/network saves, and successful save.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
