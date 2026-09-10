const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const source = fs.readFileSync(require('node:path').join(__dirname, '../templates/admin.html'), 'utf8');
const popout = source.slice(source.indexOf('function popoutSection('), source.indexOf('// Notes Management (Admin)'));
(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.MAPPROJ_BROWSER_CHANNEL || undefined});
    try {
        const page = await browser.newPage();
        await page.setContent('<div><h2>Legend Editor</h2><div id="legendEditorSection"><div id="legendEditor"><input value="RoomState1"></div></div></div>');
        await page.addScriptTag({content: popout});
        await page.evaluate(() => popoutSection('legendEditorSection'));
        assert.equal(await page.locator('#legendEditor').count(), 1, 'Popout must not duplicate editor IDs');
        await page.locator('.modal-overlay input').fill('Custom room status');
        await page.getByRole('button', {name: 'Close'}).click();
        assert.equal(await page.locator('#legendEditor input').inputValue(), 'Custom room status');
        await page.evaluate(() => popoutSection('legendEditorSection'));
        assert.equal(await page.locator('.modal-overlay input').inputValue(), 'Custom room status');
        console.log('PASS: one live legend editor; edits survive closing and reopening the popout.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
