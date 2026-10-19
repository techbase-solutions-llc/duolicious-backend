# Emails that fit a phone

Linear: TEC-1845 (found during the quick questions and Together proofs). Approved by the owner in the session on 18 Oct 2026 ("try your plan").

## The fault

Gmail on Android shows "Revert auto-sizing" on most Ahavah emails. The brand shell's card is `<table width="600" style="width:600px;max-width:100%">`. A percentage max-width cannot resolve while a table is being sized, so the email lays out 624px wide on any phone. Gmail then either rewrites it itself (auto-sizing: it reflows the layout and enlarges the text about 1.4 times while the logo, padding and title images keep their sizes) or shrinks the whole email to fit. A button label that cannot wrap (`white-space:nowrap`) makes an email wide on its own once the shell is fixed. Evidence: the owner's 9 screenshots, and the audit in the session scratchpad (`email-audit/`), measured in Chrome and WebKit at 320 to 412px.

## The changes

1. `emails/base.py` `render()`: the card table becomes `width="100%" style="width:100%;max-width:600px"`, inside an `[if mso]` 600px ghost table so desktop Outlook keeps its width.
2. `button()`: no `nowrap`; line height 1.25 so a long label wraps onto 2 lines.
3. `title_image()`: `width:100%;max-width:{w}px;height:auto`, keeping the width attribute for Outlook, so a title that fails to load cannot hold the email wide.
4. `-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%` inline on the body and the card, since Gmail drops the style block.
5. The staff and abuse emails (`waitlist_admin`, `feedback`, the NSFW notice and the report) use `base.SANS` and a fluid width; `emails/README.md` stops recommending Arial.
6. A guard, `tests/test_email_renders_on_a_phone.py`: it renders every email with sample data (`tests/email_samples.py`, from the audit's registry) and fails on any element wider than 320px outside an `[if mso]` block, on a `nowrap` button and on a sample that no longer builds.

## Not in this change, waiting on design or the owner

- The Together, checklist and deletion emails set their headlines in bold sans, not an Ultra title image. They need title images from a Claude Design brief, or the owner's waiver.
- Long one-line title images shrink to near body size on a narrow phone. They need re-exporting on 2 or 3 lines (a design brief).

## Verification

Run the API email tests. Re-measure every rendered email at 320, 360, 375 and 412 in Chrome and WebKit with the audit's `fixcheck.mjs`. Send the owner a before and after proof pair of the same email, and deploy only on his yes.
