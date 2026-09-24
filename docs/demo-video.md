# How the demo video is made

The GIF at the top of the README and `docs/media/demo.mp4` are not screen recordings: a script
drives the real app in demo mode, so the video can be regenerated whenever the interface changes
and it never shows real data.

```bash
pip install -e ".[dev]"                          # playwright, reportlab…
python scripts/make_demo.py                      # only if you change the sample invoices
python scripts/record_demo.py --chrome           # docs/media/demo.mp4 + demo.gif (~28 s)
python scripts/record_demo.py --screenshots --chrome
python scripts/record_demo.py --social --chrome  # the 1280×640 image for link previews
```

`--chrome` uses the installed Google Chrome (its PDF viewer renders the invoices); without it,
run `playwright install chromium` first. `ffmpeg` must be on the PATH.

## What the script does

1. **Starts the app in-process** with the demo settings: a fictional bistro, its ledger and
   sample invoices. The app is shown under the business's own name, the way a firm would brand
   it, not as a product. The month's invoices are read before recording starts; the emailed
   receipt is read slowly (~4 s) so the live reading can be seen.
2. **Opens a headless browser** at 1440 × 900 and injects a small overlay: a visible cursor with a
   click ripple and a caption pill. Clicks are real clicks on the real interface.
3. **Captures frames from Chrome's own screencast** (DevTools `Page.startScreencast`): sharp text,
   nothing else from the desktop. Frames arrive only when the page repaints, and only while
   Playwright is processing events, so every pause uses `page.wait_for_timeout`, never
   `time.sleep` (with `time.sleep` the animations come out as a handful of frames).
4. **Resamples to a constant 30 fps**, each output frame being the latest captured one, and pipes
   them into `ffmpeg` (H.264, CRF 20, `faststart`).
5. **Makes the GIF** in two ffmpeg passes (palette, then dithering) at 960 px and 12 fps.

## Storyboard (≈28 s)

| s | Scene | Caption |
|---|---|---|
| 0 | The month's invoices, already read; the cursor goes to *Mailbox* | Invoices arrive by email, upload or phone photo |
| 2 | A forwarded email arrives: the receipt photo is taken, the signature logo set aside | Attachments are picked up; signature logos are set aside |
| 5 | The photo is read live: fields fill in, each check ticks | Any AI model reads it: Gemini, Claude, OpenAI or a local model |
| 11 | The ticket's printed tax ID fails its check digit | Rules check every figure. This printed tax ID fails its check digit |
| 13 | *Use B87654323* → all green, approve | One click fixes it with the one in your ledger |
| 16 | A wholesaler's invoice: the wine went to 600000200 on its own | Each line goes to the right account: the wine to drinks |
| 19 | Export: A3 → Holded → Xero → QuickBooks → Sage 50, *Export* | Export to Sage 50, A3, Holded, Xero, QuickBooks, CSV… |
| 24 | The batch, ready to download | One file, ready to import |
| 26 | — | Open source · MIT · unlimited commercial use |

To change it, edit `CAPTIONS` and `run()` in `scripts/record_demo.py`.

## About the receipt

The restaurant receipt is a staged photo (`scripts/assets/cafe_norte_ticket.jpg`) with the
customer set to the demo company. Its printed tax ID really does fail the check digit, which is
why Asienta flags it and offers the one the demo ledger has for that supplier.

## Publishing the video on GitHub

GitHub plays MP4s inline only when they are uploaded through its editor: edit `README.md` on
github.com, drag `docs/media/demo.mp4` in, and GitHub inserts a `user-attachments` link that
renders as a player. Keep the GIF too: it autoplays in feeds and previews.
