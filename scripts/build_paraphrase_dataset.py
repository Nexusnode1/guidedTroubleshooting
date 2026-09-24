"""Build the corrected, alignment-audited SIIS paraphrase dataset for embedding work.

Source of truth for troubleshooting knowledge: data/original/siis_responses.json (read-only,
never modified). The audit behind the corrections below is docs/siis_alignment_audit.md.

For every row this script:
  1. Cross-checks the authored title/original_query against the real official file, so a
     later change to siis_responses.json is caught rather than silently drifting from the
     hand-authored corrections here.
  2. Uses the audited alignment, the (possibly corrected) canonical query, and 8 hand-written
     paraphrases -- never templated, never copied from the article title.
  3. Builds and validates a plan from the row's real SIIS content via the same PlanBuilder the
     live app uses, so a "corrected" row is also checked against the official schema/rules.
  4. Assigns every canonical/paraphrase text to train, val, or test, grouped by the *article*
     (not the row), so rows sharing one article never leak the same target across splits in a
     way that would let a model memorize its way to a correct test answer.

Output: data/processed/siis_paraphrase_dataset.json (git-ignored; regenerate by re-running
this script -- it is never hand-edited).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402
from app.services.plan_builder import PlanBuilder  # noqa: E402

OUT_PATH = ROOT / "data" / "processed" / "siis_paraphrase_dataset.json"

# Each entry: id, siis_title (cross-checked), original_query (cross-checked, kept for
# traceability), alignment, alignment_reason, canonical_query, corrected, paraphrases (8).
# See docs/siis_alignment_audit.md for the reasoning behind every alignment call and
# correction; do not edit paraphrase wording here without updating that document.
ROWS: list[dict[str, Any]] = [
    {
        "id": "row_1",
        "siis_title": "Email server not responding on Samsung phone or tablet",
        "original_query": "1. My Samsung A115G tablet screen flashes and then goes completely blank whenever I tap to open an email in Gmail, and after it works for a short time it goes blank again.",
        "alignment": "MISALIGNED",
        "alignment_reason": "Article is pure email-connectivity troubleshooting (Wi-Fi, cache, safe mode, contact provider); it never addresses a display symptom.",
        "corrected": True,
        "canonical_query": "My email keeps saying the server isn't responding and my messages won't load on my Samsung tablet.",
        "paraphrases": [
            "My email app can't connect to the mail server, so nothing loads.",
            "My email's being weird, it just won't sync no matter what I do.",
            "Email server not responding again.",
            "Messages aren't loading and I keep getting a 'server not responding' error in my email app.",
            "Why does my email app keep saying the server isn't responding?",
            "This is so annoying, my email has been stuck saying 'server not responding' for hours.",
            "My mail client can't reach the email server, so my inbox won't refresh.",
            "So my email just stopped working, it keeps telling me the server won't respond.",
        ],
    },
    {
        "id": "row_2",
        "siis_title": "Blank or black display on a Samsung phone or tablet",
        "original_query": "My Galaxy S22 screen turns completely blank or white and no text appears when I search for a stock price or use the Smart Tutor app, and it happens with other apps too.",
        "alignment": "MISALIGNED",
        "alignment_reason": "Query describes a device that is on and interactive (searching, using apps) with a rendering/app problem; article's flow (check damage, force restart, charge) is for a device that will not power on at all.",
        "corrected": True,
        "canonical_query": "My Galaxy S22 screen is completely blank and won't show anything, even when I try to turn it back on.",
        "paraphrases": [
            "My phone's screen stays black no matter how many times I try to turn it on.",
            "My screen's just dead, nothing shows up at all.",
            "Screen won't turn on.",
            "No image at all on my display, even after pressing the power button several times.",
            "Why won't my Galaxy's screen show anything when I try to turn it on?",
            "I've tried everything and my screen still won't come on, it's completely blank.",
            "The display isn't lighting up at all when I attempt to power on my phone.",
            "So my phone just won't display anything anymore, even trying to switch it on doesn't help.",
        ],
    },
    {
        "id": "row_3",
        "siis_title": "Some things to check first",
        "original_query": "My Galaxy Z Flip 7 screen went completely black, so I can't see or interact with the phone, and I'm unable to use Smart Switch or any other method to transfer my data.",
        "alignment": "ALIGNED",
        "alignment_reason": "Matches the article's own 'access data via USB mouse when screen is blank' plus force-restart content directly.",
        "corrected": False,
        "canonical_query": "My Galaxy Z Flip 7 screen went completely black, so I can't see or interact with the phone, and I'm unable to use Smart Switch or any other method to transfer my data.",
        "paraphrases": [
            "My phone's screen is totally black and I can't get it to respond so I can back up my data.",
            "My screen just went dark and I can't do anything with it, not even transfer my stuff.",
            "Screen's black, can't transfer data.",
            "Nothing shows on my screen at all, and Smart Switch won't work to move my files off.",
            "How do I get my data off my phone if the screen is completely black?",
            "I really need my photos off this phone but the screen is dead and Smart Switch won't even open.",
            "The display is unresponsive and totally dark, so I can't run any data transfer tool.",
            "My phone's screen won't light up at all, and I can't seem to get Smart Switch going to save my data.",
        ],
    },
    {
        "id": "row_4",
        "siis_title": "Blank or black display on a Samsung phone or tablet",
        "original_query": "My Samsung Galaxy A15/A16 screen suddenly went completely black on its own after about a month of use. It doesn't display anything, even when I try to turn it on.",
        "alignment": "ALIGNED",
        "alignment_reason": "Squarely the 'device not turning on' scenario the article addresses.",
        "corrected": False,
        "canonical_query": "My Samsung Galaxy A15/A16 screen suddenly went completely black on its own after about a month of use. It doesn't display anything, even when I try to turn it on.",
        "paraphrases": [
            "My phone's screen went black by itself and now nothing shows up when I try to turn it on.",
            "My screen just died out of nowhere, it's been fine for a month and now nothing.",
            "Screen suddenly went black.",
            "No display at all, and it happened on its own without me dropping it or anything.",
            "Why did my screen suddenly go completely black after only a month of use?",
            "I only had this phone a month and the screen just stopped working out of nowhere!",
            "The display shut off unexpectedly and won't turn back on no matter what I try.",
            "So randomly my screen just went totally black and now the phone won't show anything at all.",
        ],
    },
    {
        "id": "row_5",
        "siis_title": "Transfer Secure folder with Smart Switch",
        "original_query": "My Galaxy tablet screen stays completely blank when I try to use Smart Switch to scan the QR code for transferring data from my Galaxy S25 phone, so the transfer can't proceed.",
        "alignment": "PARTIALLY_ALIGNED",
        "alignment_reason": "Action/domain (Smart Switch QR transfer) matches; 'screen stays blank' is not a failure mode the article discusses -- it explains the normal working flow only.",
        "corrected": True,
        "canonical_query": "I'm having trouble using Smart Switch to scan the QR code and transfer my data from my old Galaxy phone to my new one.",
        "paraphrases": [
            "The QR code transfer in Smart Switch isn't working when I try to move my data to my new phone.",
            "I can't get the Smart Switch QR thing to work between my two phones.",
            "Smart Switch QR transfer isn't working.",
            "The transfer won't start even after I scan the QR code in Smart Switch.",
            "How do I get Smart Switch to actually transfer my data using the QR code?",
            "I've tried scanning the QR code several times in Smart Switch and the transfer still won't go through.",
            "Wireless data migration via Smart Switch's QR scan isn't completing between my devices.",
            "I'm trying to move everything over with Smart Switch using the QR code but it's just not going through.",
        ],
    },
    {
        "id": "row_7",
        "siis_title": "Use Multi window and App pairs on your Galaxy phone or tablet",
        "original_query": "My tablet's screen stays dark and only three app icons are lit while the rest are dark and won't open, so nothing loads on the screen and I can't use the device.",
        "alignment": "MISALIGNED",
        "alignment_reason": "A feature how-to for split screen/app pairs/Edge panel, unrelated to a mostly-dark screen with a few lit icons.",
        "corrected": True,
        "canonical_query": "I don't know how to open two apps at the same time on my Galaxy tablet using split screen.",
        "paraphrases": [
            "I can't figure out how to run two apps side by side on my tablet.",
            "How do I get two apps up on the screen at once on my Galaxy?",
            "Can't do split screen with two apps.",
            "Only one app shows on my screen at a time, I can't seem to open a second one alongside it.",
            "How do I use split screen to view two apps at the same time on my tablet?",
            "I keep trying to open two apps together and I can't work out how the split screen feature is supposed to work.",
            "I want to multitask with two apps in multi window mode but can't find how to set it up.",
            "So I heard you can have two apps open on screen together, but I have no idea how to actually do it on mine.",
        ],
    },
    {
        "id": "row_8",
        "siis_title": "Screen mirroring to your Samsung TV",
        "original_query": "My new Samsung phone's main screen stays small and doesn't fill the whole display; I can't make it expand to full size and I've never seen this before.",
        "alignment": "MISALIGNED",
        "alignment_reason": "Article is about mirroring/casting to a TV, not the phone's own native display. It does have an 'image looks small' remedy, but only in the TV-mirroring context.",
        "corrected": True,
        "canonical_query": "When I mirror my phone to my Samsung TV with Smart View, the image looks small and doesn't fill the whole TV screen.",
        "paraphrases": [
            "The picture is tiny on my TV when I use Smart View to mirror my phone.",
            "My screen mirroring looks all small and doesn't take up the whole TV.",
            "Mirrored image looks small on TV.",
            "There's a lot of empty space around the picture when I mirror my phone to the TV.",
            "How do I make the mirrored screen fill the whole TV instead of looking small?",
            "I keep mirroring my phone with Smart View and the image just stays small in the middle of the TV, it's really annoying.",
            "The aspect ratio looks off when I cast my screen to the TV, the display doesn't fill the frame.",
            "So when I cast my phone to the TV with Smart View, the picture just looks small instead of filling the screen.",
        ],
    },
    {
        "id": "row_9",
        "siis_title": "Access your Galaxy phone's data if the screen does not respond",
        "original_query": "My Galaxy Flip 7 inner screen stopped working by itself; it shows no image and doesn't respond to touch, while the outer cover screen still works.",
        "alignment": "ALIGNED",
        "alignment_reason": "Matches 'touchscreen doesn't work' / 'nothing visible on screen' directly; foldable detail is device context, not a new symptom.",
        "corrected": False,
        "canonical_query": "My Galaxy Flip 7 inner screen stopped working by itself; it shows no image and doesn't respond to touch, while the outer cover screen still works.",
        "paraphrases": [
            "The main screen on my foldable stopped showing anything and doesn't respond to touch anymore.",
            "My inside screen just died, no picture and touch doesn't do anything, but the outside one's fine.",
            "Inner screen unresponsive, no image.",
            "No display and no touch response on the main screen, though the cover screen still works.",
            "How can I get my data off my phone if the main screen won't show anything or respond to touch?",
            "My main screen just stopped working out of nowhere and I still need to get my photos off before I send it in for repair.",
            "The primary display is blank and unresponsive to touch input, while the cover display still functions normally.",
            "So the big screen on my foldable just went blank and won't respond to touch, but the little outside screen still works fine.",
        ],
    },
    {
        "id": "row_10",
        "siis_title": "Screen flickers when using the Camera on a Galaxy phone",
        "original_query": "My Samsung Galaxy Z Flip 6 screen flickers and goes blank whenever I open it, so I can't see anything or access the settings, which stops me from using the phone.",
        "alignment": "MISALIGNED",
        "alignment_reason": "Article is specifically camera-video flicker from lighting frequency, not a general system display flicker on unfolding the phone.",
        "corrected": True,
        "canonical_query": "My Galaxy phone's camera video has a flickering line or band, especially when I record indoors under fluorescent or LED lighting.",
        "paraphrases": [
            "There's a flickering band that shows up in my videos when I film inside under the lights.",
            "My camera footage keeps flickering like a black bar moving across the screen when I record indoors.",
            "Video flickers under indoor lighting.",
            "A flicker or moving line shows up in my recordings whenever I'm filming under fluorescent lights.",
            "Why does my camera video flicker when I record under LED or fluorescent lighting?",
            "Every video I take indoors has this annoying flicker running through it, I can't figure out why.",
            "My camera app produces a strobing artifact in footage captured under artificial indoor lighting.",
            "So whenever I record something indoors, there's this weird flicker or line moving through the video.",
        ],
    },
    {
        "id": "row_11",
        "siis_title": "Some things to check first",
        "original_query": "My Galaxy Flip 6 screen is half black—one side of the display is completely dark while the other side works fine, so I can't access the device normally.",
        "alignment": "PARTIALLY_ALIGNED",
        "alignment_reason": "General 'screen not working, can't use device' domain matches; 'half black' is a more specific defect the article's generic remedies don't target.",
        "corrected": True,
        "canonical_query": "Part of my Galaxy Flip 6's touchscreen is black and doesn't respond, so I can't use the phone properly.",
        "paraphrases": [
            "A section of my touchscreen is black and won't respond, making the phone hard to use.",
            "Some of my touchscreen just stays black and won't respond to touch, and I can barely use my phone.",
            "Part of the touchscreen is black and unresponsive.",
            "There's an area on my touchscreen that stays black and doesn't respond while the rest works fine.",
            "What can I do if part of my touchscreen is black and doesn't respond at all?",
            "It's so frustrating, part of my touchscreen just stays black and won't respond and I can't use my phone like normal.",
            "A portion of the touchscreen is black and unresponsive while the remainder still works.",
            "So a chunk of my touchscreen just went black and stopped responding, and now I'm struggling to actually use the phone.",
        ],
    },
    {
        "id": "row_12",
        "siis_title": "Use Multi window and App pairs on your Galaxy phone or tablet",
        "original_query": "My Galaxy S25 has a floating circle that constantly hovers on my screen and gives me quick shortcuts to recent apps, home, back, screen off, volume control, and more; I want to remove it.",
        "alignment": "MISALIGNED",
        "alignment_reason": "Described feature is an Assistant-Menu-style floating shortcut, not Multi Window/App pairs.",
        "corrected": True,
        "canonical_query": "I want to remove an app pair shortcut from the Edge panel on my Galaxy phone.",
        "paraphrases": [
            "I can't figure out how to delete an app pair I made on the Edge panel.",
            "How do I get rid of one of those app shortcuts on the side panel?",
            "Remove app pair from Edge panel.",
            "There's a shortcut I don't want anymore sitting on my Edge panel and I can't remove it.",
            "How do I remove a shortcut I no longer want from the Edge panel?",
            "I keep trying to get rid of this app pair on my Edge panel and nothing I do removes it.",
            "I need to delete an app shortcut that's cluttering my side panel.",
            "So I made an app pair a while back and now I just want it off my Edge panel, how do I do that?",
        ],
    },
    {
        "id": "row_13",
        "siis_title": "Blank or black display on a Samsung phone or tablet",
        "original_query": "My Galaxy S22 screen stays blank and doesn't show any activation message or anything else when I turn it on after the carrier deactivated the old phone.",
        "alignment": "ALIGNED",
        "alignment_reason": "'No display at power-up' matches the article; carrier-swap detail is device context.",
        "corrected": False,
        "canonical_query": "My Galaxy S22 screen stays blank and doesn't show any activation message or anything else when I turn it on after the carrier deactivated the old phone.",
        "paraphrases": [
            "My new phone's screen stays blank and shows nothing at all when I try to turn it on after switching carriers.",
            "Since I switched phones with my carrier, this one just won't show anything on the screen.",
            "Screen blank after carrier switch.",
            "No activation screen, no message, nothing shows up at all when I power the phone on.",
            "Why does my screen stay completely blank after my carrier deactivated my old phone?",
            "My carrier already deactivated my old line and now this phone won't show anything on the screen at all!",
            "The display remains unresponsive with no activation prompt appearing after the carrier transfer.",
            "So after my carrier switched my line over, this phone's screen just stays completely blank when I turn it on.",
        ],
    },
    {
        "id": "row_14",
        "siis_title": "Cracked or bleeding screen on Galaxy phone or tablet",
        "original_query": "My Galaxy phone's screen is completely cracked, it's a total crack and I can't use the device.",
        "alignment": "ALIGNED",
        "alignment_reason": "Direct match.",
        "corrected": False,
        "canonical_query": "My Galaxy phone's screen is completely cracked, it's a total crack and I can't use the device.",
        "paraphrases": [
            "My phone's screen is completely shattered and I can't use it at all.",
            "My screen's totally busted, cracked all over, can't do anything with the phone now.",
            "Screen is completely cracked.",
            "There are cracks all across my screen and the phone is basically unusable now.",
            "What are my options for repair since my screen is completely cracked?",
            "I dropped my phone and now the whole screen is cracked, I can't use it at all!",
            "The display glass is fully shattered, making the device unusable.",
            "So I dropped my phone and now the screen's a total crack, can't really use it like this.",
        ],
    },
    {
        "id": "row_15",
        "siis_title": "Blank or black display on a Samsung phone or tablet",
        "original_query": "My Galaxy S26 Ultra only shows a blue (or black) screen with tiny text when I try to turn it on, and it won't start up. I tried holding the power button but it doesn't help.",
        "alignment": "ALIGNED",
        "alignment_reason": "'Won't start up' boot failure matches the article's domain; the specific blue-screen visual is more detail than the article covers, but the core complaint and remedy fit.",
        "corrected": False,
        "canonical_query": "My Galaxy S26 Ultra only shows a blue (or black) screen with tiny text when I try to turn it on, and it won't start up. I tried holding the power button but it doesn't help.",
        "paraphrases": [
            "My phone won't start up, it just shows a blue screen with small text and holding the power button doesn't do anything.",
            "My phone's stuck on this weird blue screen with tiny writing and won't boot up no matter what.",
            "Won't start, blue screen with text.",
            "There's a blue screen with tiny text and the phone just won't finish starting up.",
            "Why won't my phone start up past this blue screen with small text?",
            "I've held the power button forever and my phone is still stuck on this blue screen, it won't start!",
            "The device is stuck at a diagnostic-looking blue screen and fails to complete booting.",
            "So my phone's just stuck showing this blue screen with tiny text and it won't actually turn on properly.",
        ],
    },
    {
        "id": "row_16",
        "siis_title": "Blank or black display on a Samsung phone or tablet",
        "original_query": "My Samsung S***** Ultra screen flashes extremely quickly (in milliseconds) whenever I plug in a charger, making the display unusable for a short period.",
        "alignment": "MISALIGNED",
        "alignment_reason": "A brief flash on an apparently functioning device is a different failure class from 'won't power on at all.'",
        "corrected": True,
        "canonical_query": "My Galaxy phone's screen is black most of the time and rarely turns on, even after I try to restart it.",
        "paraphrases": [
            "My screen just stays black, it hardly ever turns on even after restarting.",
            "My phone's screen is basically dead, black almost all the time no matter how much I restart it.",
            "Screen stays black, restart doesn't help.",
            "The display stays black and only rarely, briefly comes on, and restarting doesn't fix it.",
            "Why does my screen stay black most of the time even after I restart my phone?",
            "I keep restarting my phone and the screen just stays black, this is so frustrating.",
            "The display fails to activate reliably and remains black even after a restart.",
            "So my screen basically just stays black no matter how many times I restart the phone.",
        ],
    },
    {
        "id": "row_17",
        "siis_title": "Some things to check first",
        "original_query": "1. \"My Galaxy S24 screen goes completely blank, just a dark screen with occasional scrolling and no visible content, so I can't see anything or use Smart Switch to transfer data.\"",
        "alignment": "ALIGNED",
        "alignment_reason": "Matches the article's blank-screen/data-access/force-restart content. Canonical query drops the source list-numbering artifact ('1. \"...\"') as a formatting normalization only -- no semantic change.",
        "corrected": False,
        "canonical_query": "My Galaxy S24 screen goes completely blank, just a dark screen with occasional scrolling and no visible content, so I can't see anything or use Smart Switch to transfer data.",
        "paraphrases": [
            "My screen goes totally dark with only a bit of scrolling visible, and I can't see anything or use Smart Switch.",
            "My screen's just black with like a tiny scroll thing happening, and Smart Switch won't work either.",
            "Screen dark, can't use Smart Switch.",
            "There's occasional scrolling but no real content on my screen, and I can't get Smart Switch to transfer my data.",
            "How do I transfer my data with Smart Switch if my screen is dark and I can't see anything?",
            "My screen barely shows anything except some scrolling and Smart Switch just won't let me move my data over!",
            "The display shows minimal scrolling artifacts with no visible content, preventing me from using Smart Switch to migrate data.",
            "So my screen's basically dark except for a little scrolling now and then, and I can't get Smart Switch going to save my stuff.",
        ],
    },
    {
        "id": "row_19",
        "siis_title": "Cracked or bleeding screen on Galaxy phone or tablet",
        "original_query": "1. \"My Galaxy Z Flip 7 screen is cracked again right where it folds.\"\n2. \"The touch doesn't work on certain parts of the screen.\"\n3. \"I can hardly see anything on the display.\"",
        "alignment": "ALIGNED",
        "alignment_reason": "Multi-symptom complaint, but all three symptoms are consistent with physical screen damage. Canonical query merges the numbered list into one sentence -- formatting normalization only.",
        "corrected": False,
        "canonical_query": "My Galaxy Z Flip 7 screen is cracked again right at the fold, touch doesn't work on certain parts of the screen, and I can hardly see anything on the display.",
        "paraphrases": [
            "The screen cracked again at the fold, some spots don't respond to touch, and it's hard to see the display.",
            "My fold screen cracked again, touch is dead in some spots, and I can barely see anything.",
            "Cracked at fold again, touch and visibility broken.",
            "Touch isn't working in some areas and the display is hard to see, on top of a new crack right at the fold.",
            "What can I do about my screen cracking again at the fold along with touch and visibility problems?",
            "This is the second time it's cracked right at the fold, and now touch barely works and I can hardly see anything!",
            "The panel has fractured again at the hinge, with unresponsive touch zones and degraded visibility.",
            "So the fold cracked again, some parts don't respond to touch anymore, and honestly I can barely see the screen at this point.",
        ],
    },
    {
        "id": "row_20",
        "siis_title": "Screen does not rotate on Galaxy phone or tablet",
        "original_query": "My Galaxy A17 screen looks distorted right after I received the phone, and I need a diagnostic test.",
        "alignment": "MISALIGNED",
        "alignment_reason": "Article is about auto-rotate/orientation failing to work, a different symptom from visual distortion.",
        "corrected": True,
        "canonical_query": "My Galaxy A17's screen won't rotate to landscape when I turn the phone sideways.",
        "paraphrases": [
            "My screen doesn't rotate when I turn my phone to the side.",
            "My phone just won't flip to landscape no matter how I hold it.",
            "Screen won't rotate.",
            "Turning my phone sideways doesn't change the screen orientation at all.",
            "Why won't my screen rotate to landscape when I turn my phone?",
            "I keep turning my phone sideways and the screen just refuses to rotate, it's brand new too!",
            "The display fails to switch to landscape orientation when the device is turned.",
            "So whenever I turn my phone on its side, the screen just stays the same instead of rotating.",
        ],
    },
    {
        "id": "row_21",
        "siis_title": "Touchscreen issues on a Galaxy phone or tablet",
        "original_query": "My Galaxy S22 screen inputs are delayed and the touch responsiveness is laggy, causing a noticeable delay when I try to interact with the phone.",
        "alignment": "ALIGNED",
        "alignment_reason": "Direct match.",
        "corrected": False,
        "canonical_query": "My Galaxy S22 screen inputs are delayed and the touch responsiveness is laggy, causing a noticeable delay when I try to interact with the phone.",
        "paraphrases": [
            "My screen is slow to respond whenever I tap or swipe on it.",
            "My touchscreen feels laggy, there's a delay every time I tap something.",
            "Touch is laggy and delayed.",
            "There's a noticeable lag between when I tap the screen and when it actually responds.",
            "Why is my touchscreen so slow to respond to taps and swipes?",
            "Every tap takes forever to register, this touch delay is driving me crazy.",
            "Touch input registers with a noticeable latency across the display.",
            "So my screen just feels really sluggish, like there's always a delay before it reacts to my taps.",
        ],
    },
    {
        "id": "row_22",
        "siis_title": "Blank or black display on a Samsung phone or tablet",
        "original_query": "My Galaxy S24 Ultra screen is completely black and won't turn on, even though the phone powers on, rings, and otherwise works; there is no physical damage.",
        "alignment": "MISALIGNED",
        "alignment_reason": "Query explicitly states the device is on and functioning, directly contradicting the article's 'won't power on at all' premise -- a keyword-overlap trap ('black', 'won't turn on').",
        "corrected": True,
        "canonical_query": "My Galaxy S24 Ultra's screen is completely black and won't turn on, and there's no physical damage to the phone.",
        "paraphrases": [
            "My screen is totally black and won't turn on, even though I haven't dropped it or damaged it.",
            "My screen just won't come on at all and there's nothing wrong with it that I can see.",
            "Screen black, won't turn on, no damage.",
            "No display at all when I try to turn my phone on, and there's no visible damage anywhere.",
            "Why is my screen completely black with no display at all when there's no damage to the phone?",
            "I haven't damaged this phone at all and the screen still won't turn on, it's just black!",
            "The display remains entirely unlit and unresponsive despite no signs of physical damage.",
            "So my screen's just completely black and won't turn on, and I really haven't done anything to damage it.",
        ],
    },
]

_ROW_NUM = re.compile(r"row_(\d+)")


def _row_number(row_id: str) -> int:
    return int(_ROW_NUM.match(row_id).group(1))


def _cross_check(rows: list[dict[str, Any]], official_by_id: dict[str, Any]) -> None:
    """Fail loudly if this authored data has drifted from the real official file."""
    assert len(rows) == len(official_by_id), (
        f"authored {len(rows)} rows but data/original/siis_responses.json has {len(official_by_id)}"
    )
    for row in rows:
        official = official_by_id.get(row["id"])
        assert official is not None, f"{row['id']} is not in the official data"
        assert official["siis_response"]["title"] == row["siis_title"], (
            f"{row['id']}: authored title {row['siis_title']!r} != official {official['siis_response']['title']!r}"
        )
        assert official["original_query"] == row["original_query"], (
            f"{row['id']}: authored original_query does not match the official file verbatim"
        )
        assert row["alignment"] in {"ALIGNED", "PARTIALLY_ALIGNED", "MISALIGNED"}
        if row["alignment"] != "ALIGNED":
            assert row["corrected"], f"{row['id']}: {row['alignment']} rows must be corrected"
            assert row["canonical_query"] != row["original_query"], f"{row['id']}: marked corrected but wording is unchanged"
        assert len(row["paraphrases"]) == 8, f"{row['id']}: expected 8 paraphrases, got {len(row['paraphrases'])}"
        assert len(set(row["paraphrases"])) == 8, f"{row['id']}: paraphrases are not all distinct"
        assert row["canonical_query"] not in row["paraphrases"], f"{row['id']}: canonical query duplicated as a paraphrase"


def _group_by_article(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["siis_title"], []).append(row)
    for members in groups.values():
        members.sort(key=lambda r: _row_number(r["id"]))
    return groups


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40]


def _assign_roles(groups: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    """Return {row_id: role}. Splitting is by *article*, not by row, so rows sharing
    one article never end up training and testing on the same underlying target."""
    roles: dict[str, str] = {}
    for members in groups.values():
        if len(members) == 1:
            roles[members[0]["id"]] = "train"
            continue
        roles[members[-1]["id"]] = "held_out_test"
        if len(members) >= 3:
            roles[members[-2]["id"]] = "held_out_val"
            for row in members[:-2]:
                roles[row["id"]] = "train"
        else:
            for row in members[:-1]:
                roles[row["id"]] = "train"
    return roles


def _texts_for_row(row: dict[str, Any], role: str) -> list[dict[str, str]]:
    """Assign every canonical/paraphrase text of one row to a split, per its role."""
    if role in ("held_out_val", "held_out_test"):
        split = "val" if role == "held_out_val" else "test"
        texts = [{"text": row["canonical_query"], "kind": "canonical", "split": split}]
        texts += [{"text": p, "kind": "paraphrase", "split": split} for p in row["paraphrases"]]
        return texts
    texts = [{"text": row["canonical_query"], "kind": "canonical", "split": "train"}]
    texts += [{"text": p, "kind": "paraphrase", "split": "train"} for p in row["paraphrases"][:5]]
    texts.append({"text": row["paraphrases"][5], "kind": "paraphrase", "split": "val"})
    texts += [{"text": p, "kind": "paraphrase", "split": "test"} for p in row["paraphrases"][6:8]]
    return texts


def build_dataset() -> dict[str, Any]:
    catalog = load_catalog()
    official_by_id = {r["id"]: r for r in load_siis_rows()}
    _cross_check(ROWS, official_by_id)

    groups = _group_by_article(ROWS)
    roles = _assign_roles(groups)
    class_by_title = {title: _slug(title) for title in groups}

    builder = PlanBuilder(catalog)
    out_rows = []
    split_counts = {"train": 0, "val": 0, "test": 0}
    for row in ROWS:
        official = official_by_id[row["id"]]
        siis = official["siis_response"]
        role = roles[row["id"]]
        texts = _texts_for_row(row, role)
        for item in texts:
            split_counts[item["split"]] += 1

        build = builder.build(row["canonical_query"], siis["content"], siis["title"])
        plan_valid = build is not None and build.errors == ()
        plan_errors = list(build.errors) if build is not None else ["gated: article judged irrelevant to canonical_query"]

        out_rows.append(
            {
                "id": row["id"],
                "siis_title": row["siis_title"],
                "class_id": class_by_title[row["siis_title"]],
                "original_query": row["original_query"],
                "alignment": row["alignment"],
                "alignment_reason": row["alignment_reason"],
                "corrected": row["corrected"],
                "canonical_query": row["canonical_query"],
                "role": role,
                "paraphrases": row["paraphrases"],
                "texts": texts,
                "plan_valid": plan_valid,
                "plan_errors": plan_errors,
                "plan_title": build.response["contexts"][0]["title"] if build is not None else None,
            }
        )

    classes = [
        {"class_id": class_by_title[title], "siis_title": title, "row_ids": [r["id"] for r in members]}
        for title, members in groups.items()
    ]
    return {
        "_disclaimer": (
            "Corrected, alignment-audited paraphrase dataset for embedding evaluation/training. "
            "Canonical queries and paraphrases are author-written, not official Samsung content; "
            "the SIIS title/content each row points to is the real, unmodified official article. "
            "See docs/siis_alignment_audit.md for the audit and docs/siis_dataset_quality_report.md "
            "for the full quality report. Never a substitute for real Samsung/SIIS data, and never "
            "mixed with external intent datasets."
        ),
        "source": "data/original/siis_responses.json (read-only; this file is generated, not hand-edited)",
        "rows": out_rows,
        "classes": classes,
        "split_counts": {**split_counts, "total": sum(split_counts.values())},
    }


def main() -> int:
    dataset = build_dataset()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")

    aligned = sum(1 for r in dataset["rows"] if r["alignment"] == "ALIGNED")
    partial = sum(1 for r in dataset["rows"] if r["alignment"] == "PARTIALLY_ALIGNED")
    misaligned = sum(1 for r in dataset["rows"] if r["alignment"] == "MISALIGNED")
    corrected = sum(1 for r in dataset["rows"] if r["corrected"])
    invalid = [r["id"] for r in dataset["rows"] if not r["plan_valid"]]
    print(f"rows audited: {len(dataset['rows'])}")
    print(f"  aligned={aligned} partially_aligned={partial} misaligned={misaligned} corrected={corrected}")
    print(f"paraphrases generated: {sum(len(r['paraphrases']) for r in dataset['rows'])}")
    print(f"classes (unique articles): {len(dataset['classes'])}")
    print(f"split counts: {dataset['split_counts']}")
    print(f"plans that failed to build/validate: {invalid or 'none'}")
    print(f"wrote {OUT_PATH}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
