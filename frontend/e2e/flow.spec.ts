import { expect, test, type Page } from '@playwright/test'
import { REAL_LLM } from './env.ts'

// The whole human loop on seeded fake data: Add job -> dashboard -> gate 1 (Matches) -> gate 2
// (Review, with a chat edit) -> Queue -> submitted -> dashboard. One test, because each step
// builds on the last.
const MATCH = 'BI Developer' // awaiting_match_review, score 62
const DRAFT = 'Machine Learning Scientist' // generated, highest score (83)
// "Fake Company ..." so `seed_dev.py --reset` removes it before the next run.
const ADDED = { company: 'Fake Company 99 E2E A/S', title: 'Pasted Role For E2E' }

const tab = (page: Page, name: string) =>
  page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: new RegExp(`^${name}`) })

const tile = (page: Page, label: string) =>
  page.getByText(label, { exact: true }).locator('xpath=following-sibling::div')

test('from the dashboard through both gates to a submitted application', async ({ page }) => {
  let submittedBefore = 0

  await test.step('add job: paste a job and see it stored', async () => {
    await page.goto('/')
    await tab(page, 'Add job').click()
    await page.getByLabel('Company').fill(ADDED.company)
    await page.getByLabel('Job title').fill(ADDED.title)
    await page.getByLabel('Application URL (optional)').fill('https://jobs.example.com/e2e-added')
    await page
      .getByLabel(/Job description/)
      .fill('We need an analyst who writes Python and SQL every day. '.repeat(15))
    await expect(page.getByText(/Only \d+ words/)).toHaveCount(0)
    await page.getByRole('button', { name: 'Add job' }).click()
    await expect(page.getByRole('status')).toContainText(`Added “${ADDED.title}”`)
    await expect(page.getByLabel('Company')).toHaveValue('')
    // ENV=test makes the background run a no-op, so the row stays `new`.
    await tab(page, 'Home').click()
    const row = page.getByRole('row').filter({ hasText: ADDED.title })
    await expect(row).toContainText(ADDED.company)
    await expect(row).toContainText('new')
  })

  await test.step('dashboard shows the counts', async () => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
    await expect(tile(page, 'Applications submitted')).not.toHaveText('–')
    submittedBefore = Number(await tile(page, 'Applications submitted').innerText())
    expect(submittedBefore).toBeGreaterThanOrEqual(1) // the seed has one submitted posting
    await expect(tile(page, 'Job postings reviewed')).not.toHaveText('–')
    await expect(tile(page, 'Good matches')).not.toHaveText('–')
  })

  await test.step('gate 1: approve a match', async () => {
    await tab(page, 'Matches').click()
    const row = page.getByRole('listitem').filter({ hasText: MATCH })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByRole('status').filter({ hasText: `Approved ${MATCH}` })).toBeVisible()
  })

  await test.step('leaving Matches sends the decision', async () => {
    await tab(page, 'Review').click() // the undo window ends when the page is left
    await tab(page, 'Matches').click()
    await expect(
      page.getByRole('listitem').filter({ hasText: 'Senior Data Scientist' }),
    ).toBeVisible()
    await expect(page.getByRole('listitem').filter({ hasText: MATCH })).toHaveCount(0)
  })

  await test.step('gate 2: open the draft and view every document', async () => {
    await tab(page, 'Review').click()
    await page.getByRole('link', { name: DRAFT }).click()
    for (const name of ['CV', 'Cover letter', 'Recruiter email']) {
      await page.getByRole('tab', { name }).click()
      await expect(page.getByTestId('markdown-preview')).toContainText('Fake draft text')
    }
    await page.getByRole('tab', { name: 'Cover letter' }).click()
  })

  await test.step('chat edit: ask, review the diff, accept', async () => {
    await page.getByLabel('Ask for a change').fill('make the opening shorter')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByRole('heading', { name: 'Proposed change' })).toBeVisible({
      timeout: REAL_LLM ? 300_000 : 10_000,
    })
    await page.getByRole('button', { name: 'Accept' }).click()
    await expect(page.getByRole('heading', { name: 'Proposed change' })).toHaveCount(0)
    if (!REAL_LLM) {
      await expect(page.getByTestId('markdown-preview')).toContainText(
        'Stub edit: make the opening shorter',
      )
    }
  })

  await test.step('approve the drafts', async () => {
    await page.getByRole('button', { name: 'Approve', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Confirm approve' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Yes, approve' }).click()
    await expect(page.getByText(/It is in the Queue/)).toBeVisible()
  })

  await test.step('queue: skip ahead to the draft, mark it submitted', async () => {
    await tab(page, 'Queue').click()
    const heading = page.locator('article h2')
    await expect(heading).toBeVisible()
    for (let i = 0; i < 5; i++) {
      const current = (await heading.innerText()).trim()
      if (current === DRAFT) break
      const skipped = page.waitForResponse(
        (r) => r.url().includes('/queue/') && r.request().method() === 'POST',
      )
      await page.getByRole('button', { name: 'Skip' }).click()
      expect((await skipped).ok()).toBe(true)
      await expect(heading).not.toHaveText(current)
    }
    await expect(heading).toHaveText(DRAFT)
    await page.getByRole('button', { name: 'Mark submitted' }).click()
    await page
      .getByRole('group', { name: 'Confirm' })
      .getByRole('button', { name: 'Confirm' })
      .click()
    await expect(page.getByRole('status').filter({ hasText: 'Marked as submitted.' })).toBeVisible()
  })

  await test.step('dashboard counts the submission', async () => {
    await tab(page, 'Home').click() // leaving the Queue sends the decision
    await expect(tile(page, 'Applications submitted')).toHaveText(String(submittedBefore + 1))
  })
})
