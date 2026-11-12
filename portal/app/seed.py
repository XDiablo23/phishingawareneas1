"""
Idempotent seed of the training library + a sample policy.

Lesson text is authored defensive-awareness content; each module also links
to a real, free, open-source resource (CISA, NCSC, SANS OUCH!, and the
open-source SCORM catalogue at RansomLeak) that an admin can swap or extend.
No module hosts a lure; this is purely defensive training.
"""
from __future__ import annotations

from app import models as m

# Free / open-source awareness resources (all real, stable landing pages).
R_CISA = "https://www.cisa.gov/cybersecurity-awareness-training"
R_CISA_VIDEOS = "https://niccs.cisa.gov/workforce-development/cybersecurity-workforce-videos"
R_NCSC = "https://www.ncsc.gov.uk/guidance/phishing"
R_OUCH = "https://www.sans.org/newsletters/ouch/"
R_SCORM = "https://ransomleak.com/open-source-security-awareness-training/"


def _q(order, text, choices, correct, why):
    return dict(order=order, text=text, choices=choices, correct_index=correct,
                explanation=why)


MODULES = [
    {
        "key": "onboarding-essentials",
        "title": "Security Awareness Essentials",
        "kind": m.KIND_ONBOARDING, "level": 1, "min_seconds": 60,
        "description": "Mandatory first-day awareness: how attackers target "
                       "people, and the habits that stop them.",
        "resource_url": R_CISA,
        "lesson_html": """
<h3>Why this matters</h3>
<p>Most breaches begin with a person, not a server. Attackers phish because it
is cheaper than hacking software. Your everyday habits - checking who really
sent a message, slowing down on urgent requests, verifying before you click -
are the control that stops them.</p>
<h3>The four habits</h3>
<ul>
<li><b>Check the sender.</b> Look at the real address, not just the display
name. Hover links to see where they truly go.</li>
<li><b>Distrust urgency.</b> "Act now or your account is closed" is a pressure
tactic. Real processes give you time.</li>
<li><b>Verify out-of-band.</b> For anything sensitive - payments, credentials,
data - confirm through a known channel you looked up yourself.</li>
<li><b>Report early.</b> Reporting a suspicious email quickly protects everyone,
and is never penalised.</li>
</ul>
<p>Work through the linked CISA material, then take the short check below.</p>
""",
        "questions": [
            _q(0, "An email creates pressure to act within 15 minutes or lose "
                  "access. What is the safest first step?",
               ["Comply immediately to avoid losing access",
                "Slow down and verify through a channel you look up yourself",
                "Forward it to colleagues so they act too",
                "Reply asking if it is real"], 1,
               "Urgency is a manipulation tactic; verify out-of-band."),
            _q(1, "The display name says 'IT Service Desk' but the address is "
                  "it-desk@mail-verify-login.com. This is:",
               ["Fine - the display name is what matters",
                "A likely look-alike/spoofed sender to distrust",
                "Proof it is internal",
                "Only a problem if there is an attachment"], 1,
               "Judge the real address and domain, not the display name."),
            _q(2, "Hovering a link shows a different domain than the text. You "
                  "should:",
               ["Click - the text is what counts",
                "Not click; the mismatch is a red flag",
                "Copy it into your browser instead",
                "Click only if it uses https"], 1,
               "A text/target mismatch is a classic phishing tell."),
            _q(3, "You clicked a suspicious link by mistake. The best action is:",
               ["Say nothing and hope it was harmless",
                "Report it promptly to security",
                "Delete the email to remove evidence",
                "Turn off your computer for the day"], 1,
               "Fast reporting limits damage and is never penalised."),
            _q(4, "Out-of-band verification means:",
               ["Replying to the same email thread",
                "Confirming via a separate known channel you looked up",
                "Asking the sender to confirm in the same message",
                "Checking the email's formatting"], 1,
               "Use an independent, trusted channel to confirm."),
        ],
    },
]


MODULES += [
    {
        "key": "remediation-spotting-phishing",
        "title": "Spotting Phishing Emails",
        "kind": m.KIND_REMEDIATION, "level": 1, "min_seconds": 45,
        "description": "Assigned after a phishing-simulation failure. The "
                       "concrete red flags and what to do instead.",
        "resource_url": R_NCSC,
        "lesson_html": """
<h3>What tripped you up</h3>
<p>You interacted with a simulated phishing message. That is exactly what this
programme is for - to practise safely. Let us turn it into a habit.</p>
<h3>Red flags, concretely</h3>
<ul>
<li><b>Mismatched sender / look-alike domain</b> (paypa1.com, micros0ft-support).</li>
<li><b>Unexpected authentication prompts</b> - "re-enter your password to
continue". Legitimate systems rarely email you to re-log-in via a link.</li>
<li><b>Attachments you did not expect</b>, especially asking you to "enable
content" or macros.</li>
<li><b>Generic greetings + urgency + reward/threat</b> combined.</li>
</ul>
<h3>What to do instead</h3>
<p>Stop, hover, check the domain. If it claims to be internal, open the app or
site yourself from a bookmark - never from the email's link. Report it.</p>
""",
        "questions": [
            _q(0, "A message asks you to 'verify your mailbox' by entering your "
                  "password on a linked page. You should:",
               ["Enter it to avoid losing mail",
                "Open your mail app directly and ignore the link",
                "Enter a wrong password to test the page",
                "Forward it to IT and then log in via the link"], 1,
               "Never authenticate via an emailed link; go to the app yourself."),
            _q(1, "Which is the strongest indicator of a phishing attachment?",
               ["A PDF from a known colleague you expected",
                "A document urging you to 'enable macros/content'",
                "A file under 1 MB",
                "A .docx extension"], 1,
               "'Enable content/macros' is a common malware-delivery lure."),
            _q(2, "paypa1.com instead of paypal.com is an example of:",
               ["A safe redirect", "A look-alike domain",
                "An email signature", "A spam filter"], 1,
               "Character-swap look-alike domains impersonate real brands."),
            _q(3, "Best immediate action for a suspected phish:",
               ["Delete it silently", "Report it using the report button/process",
                "Reply to ask if it's genuine", "Unsubscribe"], 1,
               "Reporting enables the team to protect other targets."),
        ],
    },
    {
        "key": "remediation-targeted-extended",
        "title": "Advanced & Targeted Phishing (Extended)",
        "kind": m.KIND_REMEDIATION, "level": 2, "min_seconds": 90,
        "description": "Extended remediation for repeat failures: spear-phishing, "
                       "business email compromise, and process-based defence.",
        "resource_url": R_OUCH,
        "lesson_html": """
<h3>When the attacker knows your name</h3>
<p>Targeted (spear) phishing uses real details - your manager's name, a live
project, a plausible deadline. It can be flawless on the surface, so the eye is
not enough. <b>Process</b> is the defence.</p>
<h3>Process beats polish</h3>
<ul>
<li><b>Payments / bank-detail changes:</b> always confirm via a second, known
channel (a phone number you already have), regardless of how real the email
looks. This defeats Business Email Compromise.</li>
<li><b>Requests from 'the CEO' that are urgent and secret</b> are a classic BEC
pattern - authority + urgency + secrecy.</li>
<li><b>Ask "does this fit our process?"</b> If a request skips the normal steps,
that is the signal - not the spelling.</li>
</ul>
<p>Read the linked SANS OUCH! guidance, then complete the check.</p>
""",
        "questions": [
            _q(0, "A supplier emails new bank details for an overdue invoice, "
                  "marked urgent. Correct action:",
               ["Pay quickly to keep the relationship",
                "Confirm via a phone number you already hold for them",
                "Reply to the email to confirm the details",
                "Pay half now, half after"], 1,
               "Out-of-band verification defeats invoice/BEC fraud."),
            _q(1, "The hallmark combination of Business Email Compromise is:",
               ["Authority + urgency + secrecy",
                "Attachments + images",
                "Long signatures + logos",
                "External sender + https"], 0,
               "BEC leans on authority, time pressure and 'keep it quiet'."),
            _q(2, "Why is 'it looks perfect' not enough for spear-phishing?",
               ["Attackers can't write well",
                "Targeted lures can be flawless; verify by process",
                "Perfect emails are always safe",
                "Formatting proves origin"], 1,
               "Sophisticated lures have no visible tells; rely on process."),
            _q(3, "The best single question to ask on a sensitive request is:",
               ["Is it well written?",
                "Does this follow our normal process?",
                "Is there a logo?",
                "Is it marked urgent?"], 1,
               "Process-fit is the reliable test, not surface cues."),
            _q(4, "Repeated targeting of one person usually means:",
               ["They are unimportant",
                "They are a high-value target who needs extra care",
                "The filter is broken",
                "Nothing"], 1,
               "Persistent targeting signals a valuable target - raise vigilance."),
        ],
    },
]


MODULES += [
    {
        "key": "policy-acceptable-use",
        "title": "Acceptable Use & Data Handling Refresher",
        "kind": m.KIND_POLICY, "level": 1, "min_seconds": 30,
        "description": "Assigned when a new or updated policy is published: the "
                       "practical do's and don'ts of handling company data.",
        "resource_url": R_SCORM,
        "lesson_html": """
<h3>Handling data responsibly</h3>
<p>Policies exist so everyone handles information the same, safe way. When a
policy changes, this short refresher makes sure the change actually reaches
people's day-to-day habits.</p>
<ul>
<li>Use approved systems for company data; avoid personal drives/email for work
files.</li>
<li>Classify before you share - know what is confidential.</li>
<li>Lock your screen; use the password manager; enable MFA everywhere offered.</li>
<li>Report lost devices or suspected exposure immediately.</li>
</ul>
<p>Read the current policy in the Policies tab and acknowledge it after this
refresher.</p>
""",
        "questions": [
            _q(0, "Where should company files be stored?",
               ["A personal cloud drive", "Approved company systems",
                "A personal USB stick", "Personal email"], 1,
               "Keep company data in approved, managed systems."),
            _q(1, "You lose a laptop with work data. You should:",
               ["Wait to see if it turns up", "Report it immediately",
                "Buy a replacement quietly", "Nothing, it's encrypted"], 1,
               "Immediate reporting enables remote wipe and risk control."),
            _q(2, "MFA (multi-factor authentication) should be:",
               ["Enabled everywhere it is offered", "Used only for email",
                "Avoided as it's slow", "Optional for managers"], 0,
               "MFA blocks the vast majority of account-takeover attempts."),
        ],
    },
]


SAMPLE_POLICY = {
    "title": "Acceptable Use Policy",
    "version": "1.0",
    "requires_ack": True,
    "triggers_remediation": False,   # sample only; no mass assignment on seed
    "remediation_module_key": "policy-acceptable-use",
    "body_html": """
<h2>Acceptable Use Policy (Sample)</h2>
<p>This sample policy is provided so you can see the acknowledgement flow. Your
organisation should replace it with its real policy text or an uploaded PDF.</p>
<ol>
<li>Use company systems for company work; protect your credentials.</li>
<li>Do not share confidential data outside approved channels.</li>
<li>Enable MFA and keep devices patched and locked.</li>
<li>Report suspected phishing and security incidents promptly.</li>
</ol>
<p>By acknowledging, you confirm you have read and understood this policy.</p>
""",
}


def seed_content(db) -> dict:
    """Create any missing modules/questions + the sample policy + singletons.
    Idempotent: existing modules (matched by key) are left untouched."""
    created_modules = 0
    for spec in MODULES:
        if db.query(m.Module).filter_by(key=spec["key"]).first():
            continue
        mod = m.Module(
            key=spec["key"], title=spec["title"],
            description=spec.get("description", ""),
            kind=spec.get("kind", m.KIND_REMEDIATION),
            level=spec.get("level", 1),
            lesson_html=spec.get("lesson_html", ""),
            resource_url=spec.get("resource_url"),
            video_embed_url=spec.get("video_embed_url"),
            min_seconds=spec.get("min_seconds", 60),
            pass_threshold=spec.get("pass_threshold", 0.7),
        )
        db.add(mod)
        db.flush()
        for q in spec.get("questions", []):
            db.add(m.Question(
                module_id=mod.id, order=q["order"], text=q["text"],
                choices=q["choices"], correct_index=q["correct_index"],
                explanation=q.get("explanation")))
        created_modules += 1

    if not db.query(m.Policy).first():
        db.add(m.Policy(**SAMPLE_POLICY))

    if not db.query(m.TicketConfig).filter_by(id="singleton").first():
        db.add(m.TicketConfig(id="singleton"))
    if not db.query(m.Setting).filter_by(id="singleton").first():
        db.add(m.Setting(id="singleton"))

    db.commit()
    return {"modules_created": created_modules}


def ensure_seed(db) -> None:
    if db.query(m.Module).count() == 0:
        seed_content(db)
    # always make sure singletons exist
    if not db.query(m.TicketConfig).filter_by(id="singleton").first():
        db.add(m.TicketConfig(id="singleton"))
    if not db.query(m.Setting).filter_by(id="singleton").first():
        db.add(m.Setting(id="singleton"))
    db.commit()
