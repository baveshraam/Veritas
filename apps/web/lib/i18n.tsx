"use client";
import { createContext, useContext } from "react";

/* ============================================================================
 * THE KANNADA TOGGLE
 *
 * EN/KN used to control only the language of the engine's own answer text
 * (already handled server-side, per CLAUDE.md §5 — the LLM never sees
 * Kannada directly; NLLB translates the query in and the answer out). Every
 * OTHER word in the console — every button, tab, heading, tooltip and empty
 * state — stayed in English regardless of the toggle. This file is what
 * makes the toggle mean what it says: switch to Kannada and switch the whole
 * console, not just the answer.
 *
 * Two exceptions, by design: the VERITAS wordmark and the crest are a
 * brand mark, not a sentence, and stay as-is in both languages.
 *
 * Everything else this console generates by CALLING THE API — a case
 * narrative, a citation's content, a briefing paragraph, a derivation chain
 * — is prose the backend composed in English at query time and is out of
 * reach of a client-side dictionary; only `/chat` itself honours the
 * language toggle for that text today. What this file covers is every
 * string this console itself wrote into its own JSX: the chrome.
 *
 * A string with no entry below just renders in English rather than
 * breaking — coverage can always grow without anything crashing on a miss.
 * ========================================================================== */

export type Lang = "en" | "kn";

const LangContext = createContext<Lang>("en");
export const LangProvider = LangContext.Provider;
export function useLang(): Lang {
  return useContext(LangContext);
}

/** Exact-string dictionary: the English string this console renders, as it
 *  appears in the JSX, mapped to its Kannada rendering. */
const KN: Record<string, string> = {
  // ---- TopBar ----------------------------------------------------------
  "Search cases, people, districts, actions…": "ಪ್ರಕರಣಗಳು, ವ್ಯಕ್ತಿಗಳು, ಜಿಲ್ಲೆಗಳು, ಕ್ರಿಯೆಗಳನ್ನು ಹುಡುಕಿ…",
  "Search records and actions": "ದಾಖಲೆಗಳು ಮತ್ತು ಕ್ರಿಯೆಗಳನ್ನು ಹುಡುಕಿ",
  "Appearance": "ಗೋಚರತೆ",
  "Light appearance": "ಬೆಳಕಿನ ನೋಟ",
  "Dark appearance": "ಗಾಢ ನೋಟ",
  "Light": "ಬೆಳಕು",
  "Dark": "ಗಾಢ",
  "Answer language": "ಉತ್ತರದ ಭಾಷೆ",
  "Read answers aloud": "ಉತ್ತರಗಳನ್ನು ಗಟ್ಟಿಯಾಗಿ ಓದಿ",
  "Voice on": "ಧ್ವನಿ ಆನ್",
  "Voice off": "ಧ್ವನಿ ಆಫ್",
  "Save this session as a PDF": "ಈ ಸೆಷನ್ ಅನ್ನು PDF ಆಗಿ ಉಳಿಸಿ",
  "Export": "ರಫ್ತು",
  "The API is unreachable": "API ತಲುಪಲು ಸಾಧ್ಯವಾಗುತ್ತಿಲ್ಲ",
  "System status": "ಸಿಸ್ಟಂ ಸ್ಥಿತಿ",
  "Offline": "ಆಫ್‌ಲೈನ್",
  "Live": "ಲೈವ್",
  "Connecting": "ಸಂಪರ್ಕಿಸಲಾಗುತ್ತಿದೆ",
  "Records loaded": "ಲೋಡ್ ಆದ ದಾಖಲೆಗಳು",
  "Case records": "ಪ್ರಕರಣ ದಾಖಲೆಗಳು",
  "Graph nodes": "ಗ್ರಾಫ್ ನೋಡ್‌ಗಳು",
  "Graph edges": "ಗ್ರಾಫ್ ಎಡ್ಜ್‌ಗಳು",
  "Indexed documents": "ಸೂಚ್ಯಂಕಿತ ದಾಖಲೆಗಳು",
  "Record store": "ದಾಖಲೆ ಸಂಗ್ರಹ",
  "Language model": "ಭಾಷಾ ಮಾದರಿ",
  "The Veritas API did not respond.": "Veritas API ಪ್ರತಿಕ್ರಿಯಿಸಲಿಲ್ಲ.",
  "Checking the record store…": "ದಾಖಲೆ ಸಂಗ್ರಹವನ್ನು ಪರಿಶೀಲಿಸಲಾಗುತ್ತಿದೆ…",
  "Every answer is drawn from this set. Nothing outside it can be cited.":
    "ಪ್ರತಿ ಉತ್ತರವೂ ಈ ಸೆಟ್‌ನಿಂದ ಬರುತ್ತದೆ. ಇದರ ಹೊರಗಿನದನ್ನು ಉಲ್ಲೇಖಿಸಲಾಗುವುದಿಲ್ಲ.",
  "unverified": "ಅಪರಿಶೀಲಿತ",
  "Sign in at another rank": "ಬೇರೆ ಶ್ರೇಣಿಯಲ್ಲಿ ಸೈನ್ ಇನ್ ಮಾಡಿ",
  "Switch": "ಬದಲಿಸಿ",

  // ---- SessionHistory -----------------------------------------------------
  "Previous chats": "ಹಿಂದಿನ ಚಾಟ್‌ಗಳು",
  "Previous questions asked at your rank and station": "ನಿಮ್ಮ ಶ್ರೇಣಿ ಮತ್ತು ಠಾಣೆಯಲ್ಲಿ ಕೇಳಲಾದ ಹಿಂದಿನ ಪ್ರಶ್ನೆಗಳು",
  "Chat history": "ಚಾಟ್ ಇತಿಹಾಸ",
  "Loading…": "ಲೋಡ್ ಆಗುತ್ತಿದೆ…",
  "Could not load chat history.": "ಚಾಟ್ ಇತಿಹಾಸವನ್ನು ಲೋಡ್ ಮಾಡಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.",
  "No previous questions from your rank and station yet.": "ನಿಮ್ಮ ಶ್ರೇಣಿ ಮತ್ತು ಠಾಣೆಯಿಂದ ಇನ್ನೂ ಯಾವುದೇ ಹಿಂದಿನ ಪ್ರಶ್ನೆಗಳಿಲ್ಲ.",
  "Shared by rank and station, not by who is signed in.": "ಶ್ರೇಣಿ ಮತ್ತು ಠಾಣೆಯ ಮೂಲಕ ಹಂಚಿಕೊಳ್ಳಲಾಗಿದೆ, ಯಾರು ಸೈನ್ ಇನ್ ಆಗಿದ್ದಾರೆ ಎಂಬುದರ ಮೂಲಕ ಅಲ್ಲ.",

  // ---- InvestigationHeader ----------------------------------------------
  "Case under investigation": "ತನಿಖೆಯಲ್ಲಿರುವ ಪ್ರಕರಣ",
  "Person of interest": "ಆಸಕ್ತಿಯ ವ್ಯಕ್ತಿ",
  "Open investigation": "ತೆರೆದ ತನಿಖೆ",
  "Karnataka State Police — case register": "ಕರ್ನಾಟಕ ರಾಜ್ಯ ಪೊಲೀಸ್ — ಪ್ರಕರಣ ನೋಂದಣಿ",
  "Records visible at your rank": "ನಿಮ್ಮ ಶ್ರೇಣಿಯಲ್ಲಿ ಗೋಚರಿಸುವ ದಾಖಲೆಗಳು",
  " · also examining ": " · ಇದನ್ನೂ ಪರಿಶೀಲಿಸಲಾಗುತ್ತಿದೆ ",
  "Identity reconstructed from the case records by probabilistic record linkage.":
    "ಸಂಭಾವ್ಯ ದಾಖಲೆ ಜೋಡಣೆಯ ಮೂಲಕ ಪ್ರಕರಣ ದಾಖಲೆಗಳಿಂದ ಗುರುತನ್ನು ಪುನರ್ನಿರ್ಮಿಸಲಾಗಿದೆ.",
  "Ask a question, or open a case from the register to begin.":
    "ಪ್ರಶ್ನೆ ಕೇಳಿ, ಅಥವಾ ಪ್ರಾರಂಭಿಸಲು ನೋಂದಣಿಯಿಂದ ಒಂದು ಪ್ರಕರಣವನ್ನು ತೆರೆಯಿರಿ.",
  "Status": "ಸ್ಥಿತಿ",
  "In network": "ಜಾಲದಲ್ಲಿ",
  "Cited now": "ಈಗ ಉಲ್ಲೇಖಿಸಲಾಗಿದೆ",
  "On board": "ಬೋರ್ಡ್‌ನಲ್ಲಿ",
  "Investigation views": "ತನಿಖಾ ವೀಕ್ಷಣೆಗಳು",
  "This view holds the current answer": "ಈ ವೀಕ್ಷಣೆ ಪ್ರಸ್ತುತ ಉತ್ತರವನ್ನು ಹೊಂದಿದೆ",
  "Overview": "ಅವಲೋಕನ",
  "Case Register": "ಪ್ರಕರಣ ನೋಂದಣಿ",
  "Timeline": "ಕಾಲಾನುಕ್ರಮ",
  "Network": "ಜಾಲ",
  "Geography": "ಭೂಗೋಳ",
  "Hotspot Map": "ಹಾಟ್‌ಸ್ಪಾಟ್ ನಕ್ಷೆ",
  "Area Profile": "ಪ್ರದೇಶ ವಿವರ",
  "Watchlist": "ವೀಕ್ಷಣಾ ಪಟ್ಟಿ",
  "Workload": "ಕೆಲಸದ ಹೊರೆ",
  "Financial": "ಹಣಕಾಸು",
  "Offenders": "ಅಪರಾಧಿಗಳು",
  "Repeat Offenders": "ಪುನರಪರಾಧಿಗಳು",
  "Statistics": "ಅಂಕಿಅಂಶಗಳು",
  "Forecast": "ಮುನ್ಸೂಚನೆ",
  "Board": "ಬೋರ್ಡ್",
  "Under Investigation": "ತನಿಖೆಯಲ್ಲಿದೆ",
  "Chargesheeted": "ಆರೋಪಪಟ್ಟಿ ಸಲ್ಲಿಸಲಾಗಿದೆ",
  "Convicted": "ಶಿಕ್ಷೆಗೊಳಗಾಗಿದೆ",
  "Acquitted": "ಖುಲಾಸೆಗೊಳಿಸಲಾಗಿದೆ",
  "Closed": "ಮುಚ್ಚಲಾಗಿದೆ",
  "Person {id}": "ವ್ಯಕ್ತಿ {id}",
  "person {id}": "ವ್ಯಕ್ತಿ {id}",

  // ---- Workspace ----------------------------------------------------------
  "Case register": "ಪ್ರಕರಣ ನೋಂದಣಿ",
  "Every case your rank is cleared to see, independent of whichever case is open.":
    "ನಿಮ್ಮ ಶ್ರೇಣಿಗೆ ನೋಡಲು ಅನುಮತಿಸಿದ ಪ್ರತಿ ಪ್ರಕರಣ, ಪ್ರಸ್ತುತ ಯಾವ ಪ್ರಕರಣ ತೆರೆದಿದೆ ಎಂಬುದನ್ನು ಲೆಕ್ಕಿಸದೆ.",
  "Projected case volume, with the daily range the model considers likely.":
    "ಯೋಜಿತ ಪ್ರಕರಣ ಪ್ರಮಾಣ, ಮಾದರಿ ಸಂಭಾವ್ಯವೆಂದು ಪರಿಗಣಿಸುವ ದೈನಂದಿನ ವ್ಯಾಪ್ತಿಯೊಂದಿಗೆ.",
  "days ahead": "ಮುಂದಿನ ದಿನಗಳು",
  "Where are these concentrated?": "ಇವು ಎಲ್ಲಿ ಕೇಂದ್ರೀಕೃತವಾಗಿವೆ?",
  "No forecast loaded": "ಯಾವುದೇ ಮುನ್ಸೂಚನೆ ಲೋಡ್ ಆಗಿಲ್ಲ",
  "Ask for a district's trend and Veritas projects case volume forward — reconciled so a district's forecast always equals the sum of its stations.":
    "ಒಂದು ಜಿಲ್ಲೆಯ ಪ್ರವೃತ್ತಿಯನ್ನು ಕೇಳಿ ಮತ್ತು Veritas ಪ್ರಕರಣ ಪ್ರಮಾಣವನ್ನು ಮುಂದಕ್ಕೆ ಯೋಜಿಸುತ್ತದೆ — ಜಿಲ್ಲೆಯ ಮುನ್ಸೂಚನೆಯು ಯಾವಾಗಲೂ ಅದರ ಠಾಣೆಗಳ ಮೊತ್ತಕ್ಕೆ ಸಮನಾಗುವಂತೆ ಸರಿಹೊಂದಿಸಲಾಗಿದೆ.",
  "Forecast crime for the next 30 days": "ಮುಂದಿನ 30 ದಿನಗಳ ಅಪರಾಧ ಮುನ್ಸೂಚನೆ ನೀಡಿ",
  "Repeat offenders": "ಪುನರಪರಾಧಿಗಳು",
  "Most active offenders": "ಅತ್ಯಂತ ಸಕ್ರಿಯ ಅಪರಾಧಿಗಳು",
  "Ranked by how many cases on record name them — a fact the identity layer makes possible, since the raw records have no cross-case person at all.":
    "ದಾಖಲೆಯಲ್ಲಿ ಎಷ್ಟು ಪ್ರಕರಣಗಳು ಅವರನ್ನು ಹೆಸರಿಸುತ್ತವೆ ಎಂಬುದರ ಆಧಾರದ ಮೇಲೆ ಶ್ರೇಣೀಕರಿಸಲಾಗಿದೆ — ಗುರುತು ಪದರವು ಸಾಧ್ಯವಾಗಿಸಿದ ಸತ್ಯ, ಏಕೆಂದರೆ ಮೂಲ ದಾಖಲೆಗಳಲ್ಲಿ ಪ್ರಕರಣಗಳಾದ್ಯಂತ ವ್ಯಕ್ತಿ ಎಂಬುದೇ ಇಲ್ಲ.",
  "Every person named as accused on a case within your access scope — the identity layer makes this list possible at all, since the raw records have no cross-case person.":
    "ನಿಮ್ಮ ಪ್ರವೇಶ ವ್ಯಾಪ್ತಿಯೊಳಗಿನ ಒಂದು ಪ್ರಕರಣದಲ್ಲಿ ಆರೋಪಿಯಾಗಿ ಹೆಸರಿಸಲಾದ ಪ್ರತಿಯೊಬ್ಬ ವ್ಯಕ್ತಿ — ಈ ಪಟ್ಟಿಯನ್ನು ಗುರುತು ಪದರವು ಸಾಧ್ಯವಾಗಿಸಿದೆ, ಏಕೆಂದರೆ ಮೂಲ ದಾಖಲೆಗಳಲ್ಲಿ ಪ್ರಕರಣಗಳಾದ್ಯಂತ ವ್ಯಕ್ತಿ ಎಂಬುದೇ ಇಲ್ಲ.",
  "Every offender on record, within your access scope": "ದಾಖಲೆಯಲ್ಲಿರುವ ಪ್ರತಿಯೊಬ್ಬ ಅಪರಾಧಿ, ನಿಮ್ಮ ಪ್ರವೇಶ ವ್ಯಾಪ್ತಿಯೊಳಗೆ",
  "ranked": "ಶ್ರೇಣೀಕೃತ",
  "listed": "ಪಟ್ಟಿಮಾಡಲಾಗಿದೆ",
  "No repeat-offender ranking loaded": "ಯಾವುದೇ ಪುನರಪರಾಧಿ ಶ್ರೇಣಿ ಲೋಡ್ ಆಗಿಲ್ಲ",
  "No offender ranking loaded": "ಯಾವುದೇ ಅಪರಾಧಿ ಶ್ರೇಣಿ ಲೋಡ್ ಆಗಿಲ್ಲ",
  "No offender is on record in your scope": "ನಿಮ್ಮ ವ್ಯಾಪ್ತಿಯಲ್ಲಿ ಯಾವುದೇ ಅಪರಾಧಿ ದಾಖಲೆಯಲ್ಲಿಲ್ಲ",
  "Search every offender in your scope by name…": "ನಿಮ್ಮ ವ್ಯಾಪ್ತಿಯಲ್ಲಿ ಪ್ರತಿಯೊಬ್ಬ ಅಪರಾಧಿಯನ್ನು ಹೆಸರಿನ ಮೂಲಕ ಹುಡುಕಿ…",
  "Search offenders by name": "ಹೆಸರಿನ ಮೂಲಕ ಅಪರಾಧಿಗಳನ್ನು ಹುಡುಕಿ",
  "Matching “{q}”, within your access scope": "“{q}” ಗೆ ಹೊಂದಿಕೆಯಾಗುತ್ತಿದೆ, ನಿಮ್ಮ ಪ್ರವೇಶ ವ್ಯಾಪ್ತಿಯೊಳಗೆ",
  "No offender named “{q}” is on record in your scope": "ನಿಮ್ಮ ವ್ಯಾಪ್ತಿಯಲ್ಲಿ “{q}” ಹೆಸರಿನ ಯಾವುದೇ ಅಪರಾಧಿ ದಾಖಲೆಯಲ್ಲಿಲ್ಲ",
  "The search covers every offender in your access scope, not only the ranked page — this name simply isn't in the records you can see.":
    "ಹುಡುಕಾಟವು ನಿಮ್ಮ ಪ್ರವೇಶ ವ್ಯಾಪ್ತಿಯಲ್ಲಿನ ಪ್ರತಿಯೊಬ್ಬ ಅಪರಾಧಿಯನ್ನು ಒಳಗೊಂಡಿದೆ, ಶ್ರೇಣೀಕೃತ ಪುಟ ಮಾತ್ರವಲ್ಲ — ಈ ಹೆಸರು ನೀವು ನೋಡಬಹುದಾದ ದಾಖಲೆಗಳಲ್ಲಿ ಇಲ್ಲ.",
  "Case count is a recorded fact, never a risk score — this never ranks by PageRank or a model output.":
    "ಪ್ರಕರಣ ಸಂಖ್ಯೆ ಒಂದು ದಾಖಲಿತ ಸತ್ಯ, ಎಂದಿಗೂ ಅಪಾಯದ ಅಂಕ ಅಲ್ಲ — ಇದು PageRank ಅಥವಾ ಮಾದರಿ ಔಟ್‌ಪುಟ್‌ನಿಂದ ಎಂದಿಗೂ ಶ್ರೇಣೀಕರಿಸುವುದಿಲ್ಲ.",
  "Who are the repeat offenders in Bengaluru Urban?": "ಬೆಂಗಳೂರು ನಗರದಲ್ಲಿ ಪುನರಪರಾಧಿಗಳು ಯಾರು?",
  "Who is the most active offender in Bengaluru Urban?": "ಬೆಂಗಳೂರು ನಗರದಲ್ಲಿ ಅತ್ಯಂತ ಸಕ್ರಿಯ ಅಪರಾಧಿ ಯಾರು?",
  "Case statistics": "ಪ್ರಕರಣ ಅಂಕಿಅಂಶಗಳು",
  "Rates and breakdowns over the case set — not a list of individual cases.":
    "ಪ್ರಕರಣ ಗುಂಪಿನ ಮೇಲಿನ ದರಗಳು ಮತ್ತು ವಿಭಜನೆಗಳು — ಪ್ರತ್ಯೇಕ ಪ್ರಕರಣಗಳ ಪಟ್ಟಿಯಲ್ಲ.",
  "No statistics loaded": "ಯಾವುದೇ ಅಂಕಿಅಂಶ ಲೋಡ್ ಆಗಿಲ್ಲ",
  "Ask for a rate or a breakdown — conviction rate, which district has the most pending cases, how cases split by status — computed over the records you can see.":
    "ಒಂದು ದರ ಅಥವಾ ವಿಭಜನೆಯನ್ನು ಕೇಳಿ — ಶಿಕ್ಷೆಯ ದರ, ಯಾವ ಜಿಲ್ಲೆಯಲ್ಲಿ ಅತಿ ಹೆಚ್ಚು ಬಾಕಿ ಪ್ರಕರಣಗಳಿವೆ, ಸ್ಥಿತಿಯ ಪ್ರಕಾರ ಪ್ರಕರಣಗಳು ಹೇಗೆ ವಿಭಜನೆಗೊಳ್ಳುತ್ತವೆ — ನೀವು ನೋಡಬಹುದಾದ ದಾಖಲೆಗಳ ಮೇಲೆ ಲೆಕ್ಕಹಾಕಲಾಗಿದೆ.",
  "What is the conviction rate?": "ಶಿಕ್ಷೆಯ ದರ ಎಷ್ಟು?",
  "Case overview": "ಪ್ರಕರಣ ಅವಲೋಕನ",
  "What this case is, who is in it, what is still open, and what changed most recently.":
    "ಈ ಪ್ರಕರಣ ಏನು, ಇದರಲ್ಲಿ ಯಾರಿದ್ದಾರೆ, ಇನ್ನೂ ಏನು ಬಾಕಿ ಇದೆ, ಮತ್ತು ಇತ್ತೀಚೆಗೆ ಏನು ಬದಲಾಗಿದೆ.",
  "Person overview": "ವ್ಯಕ್ತಿ ಅವಲೋಕನ",
  "Who this is, the cases naming them, and what to ask next.":
    "ಇವರು ಯಾರು, ಅವರನ್ನು ಹೆಸರಿಸುವ ಪ್ರಕರಣಗಳು, ಮತ್ತು ಮುಂದೆ ಏನು ಕೇಳಬೇಕು.",
  "Back to this case": "ಈ ಪ್ರಕರಣಕ್ಕೆ ಹಿಂತಿರುಗಿ",
  "Every case your rank is cleared to see. The case you are working stays open.":
    "ನಿಮ್ಮ ಶ್ರೇಣಿಗೆ ನೋಡಲು ಅನುಮತಿಸಿದ ಪ್ರತಿ ಪ್ರಕರಣ. ನೀವು ಕೆಲಸ ಮಾಡುತ್ತಿರುವ ಪ್ರಕರಣ ತೆರೆದೇ ಇರುತ್ತದೆ.",
  "Every case your rank is cleared to see. Open one to start an investigation.":
    "ನಿಮ್ಮ ಶ್ರೇಣಿಗೆ ನೋಡಲು ಅನುಮತಿಸಿದ ಪ್ರತಿ ಪ್ರಕರಣ. ತನಿಖೆ ಪ್ರಾರಂಭಿಸಲು ಒಂದನ್ನು ತೆರೆಯಿರಿ.",
  "Crime concentration": "ಅಪರಾಧ ಕೇಂದ್ರೀಕರಣ",
  "cases located": "ಪತ್ತೆಯಾದ ಪ್ರಕರಣಗಳು",
  "hotspots": "ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳು",
  "in the strongest": "ಪ್ರಬಲದಲ್ಲಿ",
  "Cases in {main}": "{main} ನಲ್ಲಿ ಪ್ರಕರಣಗಳು",
  "No geography loaded": "ಯಾವುದೇ ಭೂಗೋಳ ಲೋಡ್ ಆಗಿಲ್ಲ",
  "Locations for a case, or hotspot density for a district, appear here. Cases are records; hotspot regions are model output.":
    "ಒಂದು ಪ್ರಕರಣದ ಸ್ಥಳಗಳು, ಅಥವಾ ಜಿಲ್ಲೆಯ ಹಾಟ್‌ಸ್ಪಾಟ್ ಸಾಂದ್ರತೆ, ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತದೆ. ಪ್ರಕರಣಗಳು ದಾಖಲೆಗಳು; ಹಾಟ್‌ಸ್ಪಾಟ್ ಪ್ರದೇಶಗಳು ಮಾದರಿ ಔಟ್‌ಪುಟ್.",
  "Show me crime hotspots": "ನನಗೆ ಅಪರಾಧ ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳನ್ನು ತೋರಿಸಿ",
  "People and connections": "ಜನರು ಮತ್ತು ಸಂಪರ್ಕಗಳು",
  "named in record": "ದಾಖಲೆಯಲ್ಲಿ ಹೆಸರಿಸಲಾಗಿದೆ",
  "Ranked by recorded case count, within your access scope": "ದಾಖಲಿತ ಪ್ರಕರಣ ಸಂಖ್ಯೆಯ ಆಧಾರದ ಮೇಲೆ ಶ್ರೇಣೀಕೃತ, ನಿಮ್ಮ ಪ್ರವೇಶ ವ್ಯಾಪ್ತಿಯೊಳಗೆ",
  "{main} — cases as recorded, with modelled hotspot density drawn over them.":
    "{main} — ದಾಖಲಿತಂತೆ ಪ್ರಕರಣಗಳು, ಅವುಗಳ ಮೇಲೆ ಮಾದರಿಯ ಹಾಟ್‌ಸ್ಪಾಟ್ ಸಾಂದ್ರತೆಯನ್ನು ಚಿತ್ರಿಸಲಾಗಿದೆ.",
  "{n} districts — cases as recorded, with modelled hotspot density drawn over them.":
    "{n} ಜಿಲ್ಲೆಗಳು — ದಾಖಲಿತಂತೆ ಪ್ರಕರಣಗಳು, ಅವುಗಳ ಮೇಲೆ ಮಾದರಿಯ ಹಾಟ್‌ಸ್ಪಾಟ್ ಸಾಂದ್ರತೆಯನ್ನು ಚಿತ್ರಿಸಲಾಗಿದೆ.",
  "People reconstructed from accused records by probabilistic linkage, connected by the cases they share.":
    "ಸಂಭಾವ್ಯ ಜೋಡಣೆಯ ಮೂಲಕ ಆರೋಪಿತ ದಾಖಲೆಗಳಿಂದ ಪುನರ್ನಿರ್ಮಿಸಲಾದ ಜನರು, ಅವರು ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳಿಂದ ಸಂಪರ್ಕಿತರಾಗಿದ್ದಾರೆ.",
  "direct": "ನೇರ",
  "wider network": "ವಿಶಾಲ ಜಾಲ",
  "communities": "ಸಮುದಾಯಗಳು",
  "Examine {name}": "{name} ಅನ್ನು ಪರಿಶೀಲಿಸಿ",
  "No network loaded": "ಯಾವುದೇ ಜಾಲ ಲೋಡ್ ಆಗಿಲ್ಲ",
  "Name a person and Veritas traces who they offend with. Without a named subject there is nothing to traverse from, and picking one would be a guess.":
    "ಒಬ್ಬ ವ್ಯಕ್ತಿಯನ್ನು ಹೆಸರಿಸಿ ಮತ್ತು Veritas ಅವರು ಯಾರೊಂದಿಗೆ ಅಪರಾಧ ಮಾಡುತ್ತಾರೆ ಎಂಬುದನ್ನು ಪತ್ತೆಹಚ್ಚುತ್ತದೆ. ಹೆಸರಿಸಿದ ವಿಷಯವಿಲ್ಲದೆ ಪ್ರಾರಂಭಿಸಲು ಏನೂ ಇಲ್ಲ, ಮತ್ತು ಒಂದನ್ನು ಆರಿಸುವುದು ಕೇವಲ ಊಹೆಯಾಗಿರುತ್ತದೆ.",
  "Who are the associates of Usha Naika?": "ಉಷಾ ನಾಯ್ಕ ಅವರ ಸಹಚರರು ಯಾರು?",
  "Financial trail": "ಹಣಕಾಸು ಜಾಡು",
  "Transfers between accounts owned by people in this investigation. Direction is preserved — money moves one way.":
    "ಈ ತನಿಖೆಯಲ್ಲಿನ ಜನರ ಒಡೆತನದ ಖಾತೆಗಳ ನಡುವಿನ ವರ್ಗಾವಣೆಗಳು. ದಿಕ್ಕನ್ನು ಕಾಪಾಡಲಾಗಿದೆ — ಹಣ ಒಂದೇ ದಿಕ್ಕಿನಲ್ಲಿ ಚಲಿಸುತ್ತದೆ.",
  "transfers": "ವರ್ಗಾವಣೆಗಳು",
  "accounts": "ಖಾತೆಗಳು",
  "No outbound trail": "ಯಾವುದೇ ಹೊರಹೋಗುವ ಜಾಡು ಇಲ್ಲ",
  "Within your access scope": "ನಿಮ್ಮ ಪ್ರವೇಶ ವ್ಯಾಪ್ತಿಯೊಳಗೆ",
  "The accounts were traced. Nothing moved out of them in the records you can see.":
    "ಖಾತೆಗಳನ್ನು ಪತ್ತೆಹಚ್ಚಲಾಗಿದೆ. ನೀವು ನೋಡಬಹುದಾದ ದಾಖಲೆಗಳಲ್ಲಿ ಅವುಗಳಿಂದ ಏನೂ ಹೊರಹೋಗಿಲ್ಲ.",
  "No outbound transfer trail": "ಯಾವುದೇ ಹೊರಹೋಗುವ ವರ್ಗಾವಣೆ ಜಾಡು ಇಲ್ಲ",
  "Show me the timeline for {name}": "{name} ಅವರ ಕಾಲಾನುಕ್ರಮವನ್ನು ತೋರಿಸಿ",
  "No money trail loaded": "ಯಾವುದೇ ಹಣ ಜಾಡು ಲೋಡ್ ಆಗಿಲ್ಲ",
  "Financial analysis follows the accounts owned by people in this case. Ask about the money trail and Veritas traces the transfers, resolving the subject from this case.":
    "ಈ ಪ್ರಕರಣದ ಜನರ ಒಡೆತನದ ಖಾತೆಗಳನ್ನು ಹಣಕಾಸು ವಿಶ್ಲೇಷಣೆ ಅನುಸರಿಸುತ್ತದೆ. ಹಣ ಜಾಡಿನ ಬಗ್ಗೆ ಕೇಳಿ ಮತ್ತು Veritas ವರ್ಗಾವಣೆಗಳನ್ನು ಪತ್ತೆಹಚ್ಚುತ್ತದೆ, ಈ ಪ್ರಕರಣದಿಂದ ವಿಷಯವನ್ನು ನಿರ್ಧರಿಸುತ್ತದೆ.",
  "Trace the money trail for this case": "ಈ ಪ್ರಕರಣದ ಹಣ ಜಾಡನ್ನು ಪತ್ತೆಹಚ್ಚಿ",
  "Financial analysis follows a person's accounts. Pick a case from the register, or name a person, then ask about the money trail.":
    "ಒಬ್ಬ ವ್ಯಕ್ತಿಯ ಖಾತೆಗಳನ್ನು ಹಣಕಾಸು ವಿಶ್ಲೇಷಣೆ ಅನುಸರಿಸುತ್ತದೆ. ನೋಂದಣಿಯಿಂದ ಒಂದು ಪ್ರಕರಣ ಆರಿಸಿ, ಅಥವಾ ಒಬ್ಬ ವ್ಯಕ್ತಿಯನ್ನು ಹೆಸರಿಸಿ, ನಂತರ ಹಣ ಜಾಡಿನ ಬಗ್ಗೆ ಕೇಳಿ.",
  "Investigation timeline": "ತನಿಖಾ ಕಾಲಾನುಕ್ರಮ",
  "One chronology across the case, the people accused in it, and money through their accounts.":
    "ಪ್ರಕರಣ, ಅದರಲ್ಲಿ ಆರೋಪಿತ ಜನರು, ಮತ್ತು ಅವರ ಖಾತೆಗಳ ಮೂಲಕ ಹಣ — ಇವುಗಳಾದ್ಯಂತ ಒಂದೇ ಕಾಲಾನುಕ್ರಮ.",
  "from records": "ದಾಖಲೆಗಳಿಂದ",
  "derived": "ಪಡೆಯಲಾಗಿದೆ",
  "Timeline unavailable": "ಕಾಲಾನುಕ್ರಮ ಲಭ್ಯವಿಲ್ಲ",
  "Building the case chronology…": "ಪ್ರಕರಣದ ಕಾಲಾನುಕ್ರಮವನ್ನು ರಚಿಸಲಾಗುತ್ತಿದೆ…",
  "No timeline loaded": "ಯಾವುದೇ ಕಾಲಾನುಕ್ರಮ ಲೋಡ್ ಆಗಿಲ್ಲ",
  "Open a case and its chronology appears here — its own dates, its accused persons' other cases, and any money that moved.":
    "ಒಂದು ಪ್ರಕರಣ ತೆರೆಯಿರಿ ಮತ್ತು ಅದರ ಕಾಲಾನುಕ್ರಮ ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತದೆ — ಅದರ ಸ್ವಂತ ದಿನಾಂಕಗಳು, ಅದರ ಆರೋಪಿತರ ಇತರ ಪ್ರಕರಣಗಳು, ಮತ್ತು ಚಲಿಸಿದ ಯಾವುದೇ ಹಣ.",
  "What happened in this case?": "ಈ ಪ್ರಕರಣದಲ್ಲಿ ಏನಾಯಿತು?",
  "Investigation board": "ತನಿಖಾ ಬೋರ್ಡ್",
  "What this investigation has established, what is still open, and what you noted. It persists across sessions and officers.":
    "ಈ ತನಿಖೆ ಏನನ್ನು ಸ್ಥಾಪಿಸಿದೆ, ಇನ್ನೂ ಏನು ಬಾಕಿ ಇದೆ, ಮತ್ತು ನೀವು ಏನನ್ನು ಗಮನಿಸಿದ್ದೀರಿ. ಇದು ಸೆಷನ್‌ಗಳು ಮತ್ತು ಅಧಿಕಾರಿಗಳಾದ್ಯಂತ ಉಳಿಯುತ್ತದೆ.",
  "No case open": "ಯಾವುದೇ ಪ್ರಕರಣ ತೆರೆದಿಲ್ಲ",
  "The board belongs to a case. Open one from the register, or ask about a FIR, and its board becomes available here.":
    "ಬೋರ್ಡ್ ಒಂದು ಪ್ರಕರಣಕ್ಕೆ ಸೇರಿದೆ. ನೋಂದಣಿಯಿಂದ ಒಂದನ್ನು ತೆರೆಯಿರಿ, ಅಥವಾ ಒಂದು FIR ಬಗ್ಗೆ ಕೇಳಿ, ಆಗ ಅದರ ಬೋರ್ಡ್ ಇಲ್ಲಿ ಲಭ್ಯವಾಗುತ್ತದೆ.",
  "Record": "ದಾಖಲೆ",
  "Derived": "ಪಡೆದದ್ದು",
  "Model": "ಮಾದರಿ",
  "Offender": "ಅಪರಾಧಿ",
  "Recorded as": "ಇದಾಗಿ ದಾಖಲಿಸಲಾಗಿದೆ",
  "Community": "ಸಮುದಾಯ",
  "Cases": "ಪ್ರಕರಣಗಳು",
  "Community {n}": "ಸಮುದಾಯ {n}",
  "Accused": "ಆರೋಪಿ",
  "Habitual": "ಅಭ್ಯಾಸಬಲ",
  "Priors": "ಪೂರ್ವ ದಾಖಲೆ",
  "Known associates group": "ಪರಿಚಿತ ಸಹಚರರ ಗುಂಪು",
  "A Louvain community over co-offending — derived from shared cases, never a legal or gang designation.":
    "ಸಹ-ಅಪರಾಧದ ಮೇಲಿನ ಒಂದು Louvain ಸಮುದಾಯ — ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳಿಂದ ಪಡೆಯಲಾಗಿದೆ, ಎಂದಿಗೂ ಕಾನೂನುಬದ್ಧ ಅಥವಾ ಗ್ಯಾಂಗ್ ಪದನಾಮವಲ್ಲ.",
  "Membership is a Louvain community over co-offending — derived from shared cases, never a legal or gang designation. Influence is a graph-position fact, not a threat score.":
    "ಸದಸ್ಯತ್ವವು ಸಹ-ಅಪರಾಧದ ಮೇಲಿನ ಒಂದು Louvain ಸಮುದಾಯ — ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳಿಂದ ಪಡೆಯಲಾಗಿದೆ, ಎಂದಿಗೂ ಕಾನೂನುಬದ್ಧ ಅಥವಾ ಗ್ಯಾಂಗ್ ಪದನಾಮವಲ್ಲ. ಪ್ರಭಾವವು ಗ್ರಾಫ್-ಸ್ಥಾನದ ಸತ್ಯ, ಅಪಾಯದ ಅಂಕವಲ್ಲ.",
  "Ranked by network influence — not a risk score": "ಜಾಲ ಪ್ರಭಾವದ ಪ್ರಕಾರ ಶ್ರೇಣೀಕರಿಸಲಾಗಿದೆ — ಅಪಾಯದ ಅಂಕವಲ್ಲ",
  "Known associate": "ಪರಿಚಿತ ಸಹಚರ",
  "Network influence": "ಜಾಲ ಪ್ರಭಾವ",
  "members": "ಸದಸ್ಯರು",
  "shared cases": "ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳು",
  "No person is in focus, so this is the largest community in the graph. Name a person or a community number to see a different one.":
    "ಯಾವುದೇ ವ್ಯಕ್ತಿ ಗಮನದಲ್ಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಇದು ಗ್ರಾಫ್‌ನಲ್ಲಿನ ಅತಿದೊಡ್ಡ ಸಮುದಾಯ. ಬೇರೊಂದನ್ನು ನೋಡಲು ಒಬ್ಬ ವ್ಯಕ್ತಿಯನ್ನು ಅಥವಾ ಸಮುದಾಯದ ಸಂಖ್ಯೆಯನ್ನು ಹೆಸರಿಸಿ.",
  ", most often {c}.": ", ಹೆಚ್ಚಾಗಿ {c}.",
  "{n} open across": "{n} ತೆರೆದಿರುವ, ಒಟ್ಟು",
  "named in these records": "ಈ ದಾಖಲೆಗಳಲ್ಲಿ ಹೆಸರಿಸಲಾಗಿದೆ",
  "who offended alongside them": "ಅವರೊಂದಿಗೆ ಅಪರಾಧ ಮಾಡಿದವರು",
  ", and {n} more reached through a chain of shared cases": ", ಮತ್ತು ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳ ಸರಪಳಿಯ ಮೂಲಕ {n} ಹೆಚ್ಚು ತಲುಪಲಾಗಿದೆ",
  "directly involved": "ನೇರವಾಗಿ ಭಾಗಿಯಾಗಿದ್ದಾರೆ",
  "direct co-offenders": "ನೇರ ಸಹ-ಅಪರಾಧಿಗಳು",
  "{n} in this network": "ಈ ಜಾಲದಲ್ಲಿ {n}",
  "{n} people in view": "ವೀಕ್ಷಣೆಯಲ್ಲಿ {n} ಜನರು",
  "{amount} traced": "{amount} ಪತ್ತೆಹಚ್ಚಲಾಗಿದೆ",
  "{a} stated in the records · {b} linked by identity resolution": "{a} ದಾಖಲೆಗಳಲ್ಲಿ ಹೇಳಲಾಗಿದೆ · {b} ಗುರುತು ಪರಿಹಾರದಿಂದ ಜೋಡಿಸಲಾಗಿದೆ",

  // ---- ChatPane -----------------------------------------------------------
  "Copilot": "ಸಹಚಾಲಕ",
  "question": "ಪ್ರಶ್ನೆ",
  "questions": "ಪ್ರಶ್ನೆಗಳು",
  "Ask an investigative question.": "ತನಿಖಾ ಪ್ರಶ್ನೆಯನ್ನು ಕೇಳಿ.",
  "Answers are drawn from the case records you are cleared to see, and every claim carries the record it came from. Where the records don't support a claim, Veritas says so rather than guessing.":
    "ನೀವು ನೋಡಲು ಅನುಮತಿಸಿದ ಪ್ರಕರಣ ದಾಖಲೆಗಳಿಂದ ಉತ್ತರಗಳನ್ನು ಪಡೆಯಲಾಗುತ್ತದೆ, ಮತ್ತು ಪ್ರತಿ ಹಕ್ಕು ಅದು ಬಂದ ದಾಖಲೆಯನ್ನು ಹೊಂದಿರುತ್ತದೆ. ದಾಖಲೆಗಳು ಒಂದು ಹಕ್ಕನ್ನು ಬೆಂಬಲಿಸದಿದ್ದಾಗ, Veritas ಊಹಿಸುವ ಬದಲು ಹಾಗೆ ಹೇಳುತ್ತದೆ.",
  "Start here": "ಇಲ್ಲಿಂದ ಆರಂಭಿಸಿ",
  "Does Usha Naika have priors?": "ಉಷಾ ನಾಯ್ಕ ಅವರಿಗೆ ಪೂರ್ವ ದಾಖಲೆ ಇದೆಯೇ?",
  "What should I ask Usha Naika?": "ಉಷಾ ನಾಯ್ಕ ಅವರನ್ನು ನಾನು ಏನು ಕೇಳಬೇಕು?",
  "Person history": "ವ್ಯಕ್ತಿ ಇತಿಹಾಸ",
  "Interrogation prep": "ವಿಚಾರಣೆ ಸಿದ್ಧತೆ",
  "Case handoff": "ಪ್ರಕರಣ ಹಸ್ತಾಂತರ",
  "Pre-filing check": "ದಾಖಲೆಪೂರ್ವ ಪರಿಶೀಲನೆ",
  "Cross-station linkage": "ಅಂತರ-ಠಾಣೆ ಸಂಪರ್ಕ",
  "Standing case watch": "ಪ್ರಕರಣ ನಿಗಾ",
  "Criminal network": "ಅಪರಾಧ ಜಾಲ",
  "Demonstration rank — not signed in": "ಪ್ರದರ್ಶನ ಶ್ರೇಣಿ — ಸೈನ್ ಇನ್ ಆಗಿಲ್ಲ",
  "No supporting records": "ಬೆಂಬಲಿಸುವ ದಾಖಲೆಗಳಿಲ್ಲ",
  "This does not mean the event did not occur — only that nothing in the records you can see establishes it. Narrow the question, name the subject, or ask at a rank with wider scope.":
    "ಘಟನೆ ಸಂಭವಿಸಲಿಲ್ಲ ಎಂದು ಇದರ ಅರ್ಥವಲ್ಲ — ನೀವು ನೋಡಬಹುದಾದ ದಾಖಲೆಗಳಲ್ಲಿ ಯಾವುದೂ ಅದನ್ನು ಸ್ಥಾಪಿಸುವುದಿಲ್ಲ ಎಂದಷ್ಟೇ ಅರ್ಥ. ಪ್ರಶ್ನೆಯನ್ನು ಸಂಕುಚಿತಗೊಳಿಸಿ, ವಿಷಯವನ್ನು ಹೆಸರಿಸಿ, ಅಥವಾ ವಿಶಾಲ ವ್ಯಾಪ್ತಿಯ ಶ್ರೇಣಿಯಲ್ಲಿ ಕೇಳಿ.",
  "The investigation could not be completed.": "ತನಿಖೆಯನ್ನು ಪೂರ್ಣಗೊಳಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.",
  "Finding": "ಶೋಧನೆ",
  "Evidence support": "ಸಾಕ್ಷ್ಯ ಬೆಂಬಲ",
  "Inspect evidence": "ಸಾಕ್ಷ್ಯವನ್ನು ಪರಿಶೀಲಿಸಿ",
  "Ask about a case, a person, a district…": "ಒಂದು ಪ್ರಕರಣ, ಒಬ್ಬ ವ್ಯಕ್ತಿ, ಒಂದು ಜಿಲ್ಲೆಯ ಬಗ್ಗೆ ಕೇಳಿ…",
  "Ask an investigative question": "ತನಿಖಾ ಪ್ರಶ್ನೆಯನ್ನು ಕೇಳಿ",
  "Ask": "ಕೇಳಿ",
  "authoritative": "ಪ್ರಾಮಾಣಿಕ",
  "None": "ಯಾವುದೂ ಇಲ್ಲ",
  "Weak": "ದುರ್ಬಲ",
  "Moderate": "ಮಧ್ಯಮ",
  "Strong": "ಬಲವಾದ",
  "corroborating": "ಪುಷ್ಟೀಕರಿಸುವ",
  "computed": "ಲೆಕ್ಕಹಾಕಲಾಗಿದೆ",
  "Does {name} have priors?": "{name} ಅವರಿಗೆ ಪೂರ್ವ ದಾಖಲೆ ಇದೆಯೇ?",
  "Who are the associates of {name}?": "{name} ಅವರ ಸಹಚರರು ಯಾರು?",
  "Who is involved in this case?": "ಈ ಪ್ರಕರಣದಲ್ಲಿ ಯಾರು ಭಾಗಿಯಾಗಿದ್ದಾರೆ?",
  "What should I investigate next?": "ಮುಂದೆ ನಾನು ಏನನ್ನು ತನಿಖೆ ಮಾಡಬೇಕು?",
  "Pin this to the case board": "ಇದನ್ನು ಪ್ರಕರಣ ಬೋರ್ಡ್‌ಗೆ ಪಿನ್ ಮಾಡಿ",
  "What should I ask {name}?": "{name} ಅವರನ್ನು ನಾನು ಏನು ಕೇಳಬೇಕು?",
  "Catch me up on this case": "ಈ ಪ್ರಕರಣದ ಬಗ್ಗೆ ನನಗೆ ಸಂಕ್ಷಿಪ್ತ ಮಾಹಿತಿ ನೀಡಿ",
  "Would this case hold up?": "ಈ ಪ್ರಕರಣ ನ್ಯಾಯಾಲಯದಲ್ಲಿ ನಿಲ್ಲುತ್ತದೆಯೇ?",
  "Who else should know about this?": "ಇದರ ಬಗ್ಗೆ ಬೇರೆ ಯಾರಿಗೆ ತಿಳಿಯಬೇಕು?",
  "Check my other cases for a match": "ಹೊಂದಾಣಿಕೆಗಾಗಿ ನನ್ನ ಇತರ ಪ್ರಕರಣಗಳನ್ನು ಪರಿಶೀಲಿಸಿ",
  "Convince me this is wrong": "ಇದು ತಪ್ಪು ಎಂದು ನನಗೆ ಮನವರಿಕೆ ಮಾಡಿ",
  "What are the crime trends?": "ಅಪರಾಧ ಪ್ರವೃತ್ತಿಗಳು ಏನು?",

  // ---- EvidencePanel / EvidenceInspector -----------------------------------
  "Evidence": "ಸಾಕ್ಷ್ಯ",
  "Nothing cited yet": "ಇನ್ನೂ ಏನೂ ಉಲ್ಲೇಖಿಸಿಲ್ಲ",
  "Every claim an answer makes appears here as the record it rests on — with what kind of source it is, and how well it supports the claim.":
    "ಒಂದು ಉತ್ತರ ಮಾಡುವ ಪ್ರತಿ ಹಕ್ಕು ಇಲ್ಲಿ ಅದು ಆಧರಿಸಿದ ದಾಖಲೆಯಾಗಿ ಕಾಣಿಸುತ್ತದೆ — ಅದು ಎಂತಹ ಮೂಲ, ಮತ್ತು ಅದು ಹಕ್ಕನ್ನು ಎಷ್ಟು ಚೆನ್ನಾಗಿ ಬೆಂಬಲಿಸುತ್ತದೆ.",
  "source": "ಮೂಲ",
  "sources": "ಮೂಲಗಳು",
  "Support": "ಬೆಂಬಲ",
  "authoritative records": "ಪ್ರಾಮಾಣಿಕ ದಾಖಲೆಗಳು",
  "corroborating findings": "ಪುಷ್ಟೀಕರಿಸುವ ಶೋಧನೆಗಳು",
  "model outputs": "ಮಾದರಿ ಔಟ್‌ಪುಟ್‌ಗಳು",
  "Close": "ಮುಚ್ಚಿ",
  "Previous source (↑)": "ಹಿಂದಿನ ಮೂಲ (↑)",
  "Next source (↓)": "ಮುಂದಿನ ಮೂಲ (↓)",
  "Close (Esc)": "ಮುಚ್ಚಿ (Esc)",
  "Record fact": "ದಾಖಲಿತ ಸತ್ಯ",
  "Derived finding": "ಪಡೆದ ಶೋಧನೆ",
  "Model output": "ಮಾದರಿ ಔಟ್‌ಪುಟ್",
  "Why this is here": "ಇದು ಏಕೆ ಇಲ್ಲಿದೆ",
  "Hide": "ಮರೆಮಾಡಿ",
  "Trace it": "ಪತ್ತೆಹಚ್ಚಿ",
  "The records this rests on, how they were combined, and what it does not establish.":
    "ಇದು ಆಧರಿಸಿದ ದಾಖಲೆಗಳು, ಅವುಗಳನ್ನು ಹೇಗೆ ಸಂಯೋಜಿಸಲಾಗಿದೆ, ಮತ್ತು ಇದು ಏನನ್ನು ಸ್ಥಾಪಿಸುವುದಿಲ್ಲ.",
  "Provenance": "ಮೂಲ ಪ್ರಮಾಣ",
  "How this was retrieved": "ಇದನ್ನು ಹೇಗೆ ಪಡೆಯಲಾಯಿತು",
  "Stated directly in the case records": "ಪ್ರಕರಣ ದಾಖಲೆಗಳಲ್ಲಿ ನೇರವಾಗಿ ಹೇಳಲಾಗಿದೆ",
  "Inferred by Veritas from the records": "ದಾಖಲೆಗಳಿಂದ Veritas ಊಹಿಸಿದೆ",
  "Computed by a model — decision support": "ಮಾದರಿಯಿಂದ ಲೆಕ್ಕಹಾಕಲಾಗಿದೆ — ನಿರ್ಧಾರ ಬೆಂಬಲ",
  "Source {i}, {label}": "ಮೂಲ {i}, {label}",
  "Source {i} of {total}": "ಮೂಲ {total} ರಲ್ಲಿ {i}",
  "Read it in the text above rather than as a second percentage here.":
    "ಇಲ್ಲಿ ಎರಡನೇ ಶೇಕಡಾವಾರಾಗಿ ಅಲ್ಲ, ಮೇಲಿನ ಪಠ್ಯದಲ್ಲಿ ಅದನ್ನು ಓದಿ.",
  // PROV_MEANING (lib/evidence.ts)
  "Stated directly in the case records.": "ಪ್ರಕರಣ ದಾಖಲೆಗಳಲ್ಲಿ ನೇರವಾಗಿ ಹೇಳಲಾಗಿದೆ.",
  "Inferred by Veritas from the records — not written in any one of them.":
    "ದಾಖಲೆಗಳಿಂದ Veritas ಊಹಿಸಿದೆ — ಅವುಗಳಲ್ಲಿ ಯಾವುದರಲ್ಲೂ ಬರೆಯಲಾಗಿಲ್ಲ.",
  "Computed by a model. Decision support, not a recorded fact.":
    "ಮಾದರಿಯಿಂದ ಲೆಕ್ಕಹಾಕಲಾಗಿದೆ. ನಿರ್ಧಾರ ಬೆಂಬಲ, ದಾಖಲಿತ ಸತ್ಯವಲ್ಲ.",
  "Written by an investigator. Not a database fact.":
    "ತನಿಖಾಧಿಕಾರಿ ಬರೆದಿದ್ದಾರೆ. ಡೇಟಾಬೇಸ್ ಸತ್ಯವಲ್ಲ.",
  // CONF_MEANING
  "How well the records corroborate this claim.": "ದಾಖಲೆಗಳು ಈ ಹಕ್ಕನ್ನು ಎಷ್ಟು ಚೆನ್ನಾಗಿ ಪುಷ್ಟೀಕರಿಸುತ್ತವೆ.",
  "How closely the wording matches — not how true the claim is.":
    "ಪದಗಳು ಎಷ್ಟು ನಿಕಟವಾಗಿ ಹೊಂದಿಕೆಯಾಗುತ್ತವೆ — ಹಕ್ಕು ಎಷ್ಟು ಸತ್ಯ ಎಂಬುದಲ್ಲ.",
  "The model's own figure, already stated in the text.": "ಮಾದರಿಯ ಸ್ವಂತ ಅಂಕಿ, ಈಗಾಗಲೇ ಪಠ್ಯದಲ್ಲಿ ಹೇಳಲಾಗಿದೆ.",
  // sourceLabel (lib/evidence.ts SOURCE_LABEL)
  "FIR record": "FIR ದಾಖಲೆ",
  "Criminal record": "ಅಪರಾಧ ದಾಖಲೆ",
  "Relationship between people": "ಜನರ ನಡುವಿನ ಸಂಬಂಧ",
  "Network community": "ಜಾಲ ಸಮುದಾಯ",
  "Model prediction": "ಮಾದರಿ ಮುನ್ಸೂಚನೆ",
  "Geospatial analysis": "ಭೌಗೋಳಿಕ ವಿಶ್ಲೇಷಣೆ",
  "Retrieved": "ಪಡೆಯಲಾಗಿದೆ",
  "Pin to board": "ಬೋರ್ಡ್‌ಗೆ ಪಿನ್ ಮಾಡಿ",
  "Save this to the open case's investigation board": "ಇದನ್ನು ತೆರೆದ ಪ್ರಕರಣದ ತನಿಖಾ ಬೋರ್ಡ್‌ಗೆ ಉಳಿಸಿ",
  "Open case briefing": "ಪ್ರಕರಣ ಸಂಕ್ಷಿಪ್ತ ವರದಿ ತೆರೆಯಿರಿ",
  "Open case board": "ಪ್ರಕರಣ ಬೋರ್ಡ್ ತೆರೆಯಿರಿ",

  // ---- CommandPalette -------------------------------------------------------
  "Show crime hotspots": "ಅಪರಾಧ ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳನ್ನು ತೋರಿಸಿ",
  "Show crime trends": "ಅಪರಾಧ ಪ್ರವೃತ್ತಿಗಳನ್ನು ತೋರಿಸಿ",
  "Show the network around {name}": "{name} ಸುತ್ತಲಿನ ಜಾಲವನ್ನು ತೋರಿಸಿ",
  "Check whether {name} has priors": "{name} ಅವರಿಗೆ ಪೂರ್ವ ದಾಖಲೆ ಇದೆಯೇ ಎಂದು ಪರಿಶೀಲಿಸಿ",
  "Open this case's investigation board": "ಈ ಪ್ರಕರಣದ ತನಿಖಾ ಬೋರ್ಡ್ ತೆರೆಯಿರಿ",
  "Open this case's briefing": "ಈ ಪ್ರಕರಣದ ಸಂಕ್ಷಿಪ್ತ ವರದಿ ತೆರೆಯಿರಿ",
  "Answer in Kannada": "ಕನ್ನಡದಲ್ಲಿ ಉತ್ತರಿಸಿ",
  "Answer in English": "ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಉತ್ತರಿಸಿ",
  "Language": "ಭಾಷೆ",
  "Export this session": "ಈ ಸೆಷನ್ ಅನ್ನು ರಫ್ತು ಮಾಡಿ",
  "PDF": "PDF",
  "Person": "ವ್ಯಕ್ತಿ",
  "Case": "ಪ್ರಕರಣ",
  "Briefing": "ಸಂಕ್ಷಿಪ್ತ ವರದಿ",
  "Next steps": "ಮುಂದಿನ ಹೆಜ್ಜೆಗಳು",
  "FIR number, crime, district, station, section, MO, or a name…":
    "FIR ಸಂಖ್ಯೆ, ಅಪರಾಧ, ಜಿಲ್ಲೆ, ಠಾಣೆ, ಸೆಕ್ಷನ್, ವಿಧಾನ, ಅಥವಾ ಒಂದು ಹೆಸರು…",
  "Searching the register…": "ನೋಂದಣಿಯಲ್ಲಿ ಹುಡುಕಲಾಗುತ್ತಿದೆ…",
  "Command palette": "ಆಜ್ಞಾ ಫಲಕ",
  "No record matches every word of “{q}”. Press Enter to ask it as a question instead.":
    "“{q}” ನ ಪ್ರತಿ ಪದವನ್ನೂ ಹೊಂದಿಕೆಯಾಗುವ ಯಾವುದೇ ದಾಖಲೆ ಇಲ್ಲ. ಬದಲಿಗೆ ಇದನ್ನು ಪ್ರಶ್ನೆಯಾಗಿ ಕೇಳಲು Enter ಒತ್ತಿ.",
  "Records": "ದಾಖಲೆಗಳು",
  "Actions": "ಕ್ರಿಯೆಗಳು",
  "matched": "ಹೊಂದಿಕೆಯಾಗಿದೆ",
  "navigate": "ಚಲಿಸಿ",
  "open": "ತೆರೆಯಿರಿ",
  "close": "ಮುಚ್ಚಿ",

  // ---- Board ----------------------------------------------------------------
  "Established": "ಸ್ಥಾಪಿತ",
  "What this investigation has settled": "ಈ ತನಿಖೆ ಏನನ್ನು ಇತ್ಯರ್ಥಗೊಳಿಸಿದೆ",
  "Leads": "ಸುಳಿವುಗಳು",
  "Lines of enquiry, open and closed": "ವಿಚಾರಣೆಯ ಎಳೆಗಳು, ತೆರೆದ ಮತ್ತು ಮುಚ್ಚಿದ",
  "Open questions": "ಬಾಕಿ ಪ್ರಶ್ನೆಗಳು",
  "Still unanswered": "ಇನ್ನೂ ಉತ್ತರಿಸದ",
  "Investigator notes": "ತನಿಖಾಧಿಕಾರಿ ಟಿಪ್ಪಣಿಗಳು",
  "Written by an officer, not by the records": "ಅಧಿಕಾರಿ ಬರೆದಿದ್ದು, ದಾಖಲೆಗಳಿಂದಲ್ಲ",
  "This board is not available": "ಈ ಬೋರ್ಡ್ ಲಭ್ಯವಿಲ್ಲ",
  "Opening the board…": "ಬೋರ್ಡ್ ತೆರೆಯಲಾಗುತ್ತಿದೆ…",
  "Nothing on this board yet": "ಈ ಬೋರ್ಡ್‌ನಲ್ಲಿ ಇನ್ನೂ ಏನೂ ಇಲ್ಲ",
  "Ask a question about this case, then say “pin this” to keep the record, or write a note or a lead below. Everything you add stays with the case — across sessions, and for the next officer on it.":
    "ಈ ಪ್ರಕರಣದ ಬಗ್ಗೆ ಪ್ರಶ್ನೆ ಕೇಳಿ, ನಂತರ ದಾಖಲೆಯನ್ನು ಉಳಿಸಿಕೊಳ್ಳಲು “ಇದನ್ನು ಪಿನ್ ಮಾಡಿ” ಎಂದು ಹೇಳಿ, ಅಥವಾ ಕೆಳಗೆ ಟಿಪ್ಪಣಿ ಅಥವಾ ಸುಳಿವನ್ನು ಬರೆಯಿರಿ. ನೀವು ಸೇರಿಸುವ ಎಲ್ಲವೂ ಪ್ರಕರಣದೊಂದಿಗೆ ಉಳಿಯುತ್ತದೆ — ಸೆಷನ್‌ಗಳಾದ್ಯಂತ, ಮತ್ತು ಮುಂದಿನ ಅಧಿಕಾರಿಗಾಗಿ.",
  "Note": "ಟಿಪ್ಪಣಿ",
  "Pinned record": "ಪಿನ್ ಮಾಡಿದ ದಾಖಲೆ",
  "Investigative lead": "ತನಿಖಾ ಸುಳಿವು",
  "Investigator note": "ತನಿಖಾಧಿಕಾರಿ ಟಿಪ್ಪಣಿ",
  "Reason:": "ಕಾರಣ:",
  "{pct}% support at pinning": "ಪಿನ್ ಮಾಡುವಾಗ {pct}% ಬೆಂಬಲ",
  "{pct}% text match": "{pct}% ಪಠ್ಯ ಹೊಂದಾಣಿಕೆ",
  "Mark pursued": "ಅನುಸರಿಸಲಾಗುತ್ತಿದೆ ಎಂದು ಗುರುತಿಸಿ",
  "Dismiss": "ವಜಾಗೊಳಿಸಿ",
  "Reopen": "ಪುನಃ ತೆರೆಯಿರಿ",
  "Mark resolved": "ಇತ್ಯರ್ಥವಾಯಿತು ಎಂದು ಗುರುತಿಸಿ",
  "Remove": "ತೆಗೆದುಹಾಕಿ",
  "Write a note…": "ಟಿಪ್ಪಣಿ ಬರೆಯಿರಿ…",
  "Write an investigator note": "ತನಿಖಾಧಿಕಾರಿ ಟಿಪ್ಪಣಿ ಬರೆಯಿರಿ",
  "Add note": "ಟಿಪ್ಪಣಿ ಸೇರಿಸಿ",
  "Record a lead…": "ಸುಳಿವನ್ನು ದಾಖಲಿಸಿ…",
  "Record an investigative lead": "ತನಿಖಾ ಸುಳಿವನ್ನು ದಾಖಲಿಸಿ",
  "Save lead": "ಸುಳಿವನ್ನು ಉಳಿಸಿ",
  "status:open": "ತೆರೆದ",
  "status:pursued": "ಅನುಸರಿಸಲಾಗುತ್ತಿದೆ",
  "status:dismissed": "ವಜಾಗೊಳಿಸಲಾಗಿದೆ",
  "status:resolved": "ಇತ್ಯರ್ಥವಾಗಿದೆ",

  // ---- Copilot ---------------------------------------------------------------
  "Case briefing": "ಪ್ರಕರಣ ಸಂಕ್ಷಿಪ್ತ ವರದಿ",
  "Timeline unavailable.": "ಕಾಲಾನುಕ್ರಮ ಲಭ್ಯವಿಲ್ಲ.",
  "Building the chronology…": "ಕಾಲಾನುಕ್ರಮವನ್ನು ರಚಿಸಲಾಗುತ್ತಿದೆ…",
  "The briefing could not be prepared.": "ಸಂಕ್ಷಿಪ್ತ ವರದಿಯನ್ನು ಸಿದ್ಧಪಡಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.",
  "Preparing the briefing": "ಸಂಕ್ಷಿಪ್ತ ವರದಿ ಸಿದ್ಧಪಡಿಸಲಾಗುತ್ತಿದೆ",
  "The case-diary paragraph is written by the reasoning model. On a cold start this takes up to 30 seconds.":
    "ಪ್ರಕರಣ-ದಿನಚರಿ ಪ್ಯಾರಾಗ್ರಾಫ್ ಅನ್ನು ತಾರ್ಕಿಕ ಮಾದರಿ ಬರೆಯುತ್ತದೆ. ಕೋಲ್ಡ್ ಸ್ಟಾರ್ಟ್‌ನಲ್ಲಿ ಇದು 30 ಸೆಕೆಂಡುಗಳವರೆಗೆ ತೆಗೆದುಕೊಳ್ಳುತ್ತದೆ.",
  "Chronology": "ಕಾಲಾನುಕ್ರಮ",
  "No dated events on record.": "ದಾಖಲೆಯಲ್ಲಿ ದಿನಾಂಕದ ಘಟನೆಗಳಿಲ್ಲ.",
  "Cases with a similar method": "ಒಂದೇ ರೀತಿಯ ವಿಧಾನ ಹೊಂದಿರುವ ಪ್ರಕರಣಗಳು",
  "No comparable case found.": "ಹೋಲಿಸಬಹುದಾದ ಯಾವುದೇ ಪ್ರಕರಣ ಕಂಡುಬಂದಿಲ್ಲ.",
  "text match": "ಪಠ್ಯ ಹೊಂದಾಣಿಕೆ",
  "Recommended next steps": "ಶಿಫಾರಸು ಮಾಡಿದ ಮುಂದಿನ ಹೆಜ್ಜೆಗಳು",
  "No lead could be drawn from the records.": "ದಾಖಲೆಗಳಿಂದ ಯಾವುದೇ ಸುಳಿವು ಪಡೆಯಲಾಗಲಿಲ್ಲ.",
  "Draft case-diary entry": "ಕರಡು ಪ್ರಕರಣ-ದಿನಚರಿ ನಮೂದು",
  "Copied": "ನಕಲಿಸಲಾಗಿದೆ",
  "Copy": "ನಕಲಿಸಿ",
  "Written by the reasoning model from the records above. Read it before it goes in the diary.":
    "ಮೇಲಿನ ದಾಖಲೆಗಳಿಂದ ತಾರ್ಕಿಕ ಮಾದರಿ ಇದನ್ನು ಬರೆದಿದೆ. ಇದು ದಿನಚರಿಯಲ್ಲಿ ಹೋಗುವ ಮೊದಲು ಓದಿ.",

  // ---- CaseOverview / PersonOverview -----------------------------------------
  "This case could not be opened": "ಈ ಪ್ರಕರಣವನ್ನು ತೆರೆಯಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ",
  "Opening the case…": "ಪ್ರಕರಣ ತೆರೆಯಲಾಗುತ್ತಿದೆ…",
  "What happened": "ಏನಾಯಿತು",
  "No narrative on record.": "ದಾಖಲೆಯಲ್ಲಿ ವಿವರಣೆ ಇಲ್ಲ.",
  "Filed": "ದಾಖಲಿಸಲಾಗಿದೆ",
  "Station": "ಠಾಣೆ",
  "District": "ಜಿಲ್ಲೆ",
  "Sections": "ಸೆಕ್ಷನ್‌ಗಳು",
  "FIR": "FIR",
  "People in this case": "ಈ ಪ್ರಕರಣದಲ್ಲಿನ ಜನರು",
  "No accused named on this FIR.": "ಈ FIR ನಲ್ಲಿ ಯಾವುದೇ ಆರೋಪಿಯನ್ನು ಹೆಸರಿಸಿಲ್ಲ.",
  "Victims": "ಬಲಿಪಶುಗಳು",
  "Still open": "ಇನ್ನೂ ಬಾಕಿ",
  "Nothing is on this case's board yet. Ask a question and pin what matters, or record a lead — it stays with the case for the next officer on it.":
    "ಈ ಪ್ರಕರಣದ ಬೋರ್ಡ್‌ನಲ್ಲಿ ಇನ್ನೂ ಏನೂ ಇಲ್ಲ. ಪ್ರಶ್ನೆ ಕೇಳಿ ಮತ್ತು ಮುಖ್ಯವಾದದ್ದನ್ನು ಪಿನ್ ಮಾಡಿ, ಅಥವಾ ಒಂದು ಸುಳಿವನ್ನು ದಾಖಲಿಸಿ — ಇದು ಮುಂದಿನ ಅಧಿಕಾರಿಗಾಗಿ ಪ್ರಕರಣದೊಂದಿಗೆ ಉಳಿಯುತ್ತದೆ.",
  "Question": "ಪ್ರಶ್ನೆ",
  "pinned to this case's board.": "ಈ ಪ್ರಕರಣದ ಬೋರ್ಡ್‌ಗೆ ಪಿನ್ ಮಾಡಲಾಗಿದೆ.",
  "Open the case briefing": "ಪ್ರಕರಣ ಸಂಕ್ಷಿಪ್ತ ವರದಿ ತೆರೆಯಿರಿ",
  "Most recent developments": "ಇತ್ತೀಚಿನ ಬೆಳವಣಿಗೆಗಳು",
  "dated events in all": "ಒಟ್ಟು ದಿನಾಂಕದ ಘಟನೆಗಳು",
  "{n} dated events in all": "ಒಟ್ಟು {n} ದಿನಾಂಕದ ಘಟನೆಗಳು",
  "accused": "ಆರೋಪಿ",
  "victim": "ಬಲಿಪಶು",
  "victims": "ಬಲಿಪಶುಗಳು",
  "lead(s)": "ಸುಳಿವು(ಗಳು)",
  "{n} item(s) pinned to this case's board.": "{n} ಐಟಂ(ಗಳು) ಈ ಪ್ರಕರಣದ ಬೋರ್ಡ್‌ಗೆ ಪಿನ್ ಮಾಡಲಾಗಿದೆ.",
  "Ask Veritas about this case": "ಈ ಪ್ರಕರಣದ ಬಗ್ಗೆ Veritas ಅನ್ನು ಕೇಳಿ",
  "Are there similar cases?": "ಇದೇ ರೀತಿಯ ಪ್ರಕರಣಗಳಿವೆಯೇ?",
  "Show me the timeline for this case": "ಈ ಪ್ರಕರಣದ ಕಾಲಾನುಕ್ರಮವನ್ನು ತೋರಿಸಿ",
  "years": "ವರ್ಷಗಳು",
  "Name withheld at your rank": "ನಿಮ್ಮ ಶ್ರೇಣಿಯಲ್ಲಿ ಹೆಸರನ್ನು ತಡೆಹಿಡಿಯಲಾಗಿದೆ",
  "No other case linked to this identity": "ಈ ಗುರುತಿಗೆ ಯಾವುದೇ ಇತರ ಪ್ರಕರಣ ಜೋಡಿಸಿಲ್ಲ",
  "linked to this identity": "ಈ ಗುರುತಿಗೆ ಜೋಡಿಸಲಾಗಿದೆ",
  "{n} other case linked to this identity": "{n} ಇತರ ಪ್ರಕರಣಗಳು ಈ ಗುರುತಿಗೆ ಜೋಡಿಸಲಾಗಿದೆ",
  "Examine": "ಪರಿಶೀಲಿಸಿ",
  "Associates": "ಸಹಚರರು",
  "Recorded elsewhere as": "ಬೇರೆಡೆ ಹೀಗೆ ದಾಖಲಿಸಲಾಗಿದೆ",
  "— the same person, matched across case files by identity resolution.":
    "— ಅದೇ ವ್ಯಕ್ತಿ, ಗುರುತು ಇತ್ಯರ್ಥದ ಮೂಲಕ ಪ್ರಕರಣ ಫೈಲ್‌ಗಳಾದ್ಯಂತ ಹೊಂದಿಸಲಾಗಿದೆ.",
  "This person could not be opened": "ಈ ವ್ಯಕ್ತಿಯನ್ನು ತೆರೆಯಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ",
  "Opening the identity…": "ಗುರುತನ್ನು ತೆರೆಯಲಾಗುತ್ತಿದೆ…",
  "Who this is": "ಇವರು ಯಾರು",
  "Identity reconstructed across case records by probabilistic record linkage — the organizers' schema has no person, only per-case accused rows; this is the platform inferring that the same individual appears more than once.":
    "ಸಂಭಾವ್ಯ ದಾಖಲೆ ಜೋಡಣೆಯ ಮೂಲಕ ಪ್ರಕರಣ ದಾಖಲೆಗಳಾದ್ಯಂತ ಗುರುತನ್ನು ಪುನರ್ನಿರ್ಮಿಸಲಾಗಿದೆ — ಆಯೋಜಕರ ಸ್ಕೀಮಾದಲ್ಲಿ ವ್ಯಕ್ತಿ ಎಂಬುದೇ ಇಲ್ಲ, ಪ್ರಕರಣಕ್ಕೊಂದು ಆರೋಪಿತ ಸಾಲುಗಳಷ್ಟೇ ಇವೆ; ಇದೇ ವ್ಯಕ್ತಿ ಒಂದಕ್ಕಿಂತ ಹೆಚ್ಚು ಬಾರಿ ಕಾಣಿಸುತ್ತಾರೆ ಎಂದು ವೇದಿಕೆ ಊಹಿಸುತ್ತಿದೆ.",
  "Habitual offender": "ಅಭ್ಯಾಸಬಲ ಅಪರಾಧಿ",
  "Cases naming this person": "ಈ ವ್ಯಕ್ತಿಯನ್ನು ಹೆಸರಿಸುವ ಪ್ರಕರಣಗಳು",
  "No cases on record within your access scope.": "ನಿಮ್ಮ ಪ್ರವೇಶ ವ್ಯಾಪ್ತಿಯೊಳಗೆ ದಾಖಲೆಯಲ್ಲಿ ಯಾವುದೇ ಪ್ರಕರಣಗಳಿಲ್ಲ.",
  "Ask Veritas about this person": "ಈ ವ್ಯಕ್ತಿಯ ಬಗ್ಗೆ Veritas ಅನ್ನು ಕೇಳಿ",
  "Where did {name}'s money go?": "{name} ಅವರ ಹಣ ಎಲ್ಲಿ ಹೋಯಿತು?",

  // ---- CaseExplorer -----------------------------------------------------------
  "Search by FIR number, crime, district or method…": "FIR ಸಂಖ್ಯೆ, ಅಪರಾಧ, ಜಿಲ್ಲೆ ಅಥವಾ ವಿಧಾನದ ಮೂಲಕ ಹುಡುಕಿ…",
  "Search the case register": "ಪ್ರಕರಣ ನೋಂದಣಿಯನ್ನು ಹುಡುಕಿ",
  "Crime": "ಅಪರಾಧ",
  "This rank was entered without a verified badge, so no record-scoped answer can be shown. Switch and sign in with a real badge to see the case register.":
    "ಈ ಶ್ರೇಣಿಯನ್ನು ಪರಿಶೀಲಿತ ಬ್ಯಾಡ್ಜ್ ಇಲ್ಲದೆ ಪ್ರವೇಶಿಸಲಾಗಿದೆ, ಆದ್ದರಿಂದ ಯಾವುದೇ ದಾಖಲೆ-ವ್ಯಾಪ್ತಿಯ ಉತ್ತರವನ್ನು ತೋರಿಸಲಾಗುವುದಿಲ್ಲ. ಪ್ರಕರಣ ನೋಂದಣಿಯನ್ನು ನೋಡಲು ಬದಲಿಸಿ ಮತ್ತು ನಿಜವಾದ ಬ್ಯಾಡ್ಜ್‌ನೊಂದಿಗೆ ಸೈನ್ ಇನ್ ಮಾಡಿ.",
  "The case register could not be loaded": "ಪ್ರಕರಣ ನೋಂದಣಿಯನ್ನು ಲೋಡ್ ಮಾಡಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ",
  "Loading the register…": "ನೋಂದಣಿಯನ್ನು ಲೋಡ್ ಮಾಡಲಾಗುತ್ತಿದೆ…",
  "Open case {fir}": "ಪ್ರಕರಣ {fir} ತೆರೆಯಿರಿ",
  "No case matches that filter": "ಆ ಫಿಲ್ಟರ್‌ಗೆ ಯಾವುದೇ ಪ್ರಕರಣ ಹೊಂದಿಕೆಯಾಗುವುದಿಲ್ಲ",
  "Clear a facet, or search a different FIR number, district or method.":
    "ಒಂದು ಫೇಸೆಟ್ ತೆರವುಗೊಳಿಸಿ, ಅಥವಾ ಬೇರೆ FIR ಸಂಖ್ಯೆ, ಜಿಲ್ಲೆ ಅಥವಾ ವಿಧಾನವನ್ನು ಹುಡುಕಿ.",
  "visible at your rank": "ನಿಮ್ಮ ಶ್ರೇಣಿಯಲ್ಲಿ ಗೋಚರಿಸುತ್ತದೆ",

  // ---- NetworkFinding -----------------------------------------------------------
  "Who this network shows": "ಈ ಜಾಲ ಏನನ್ನು ತೋರಿಸುತ್ತದೆ",
  "Offended alongside {name}": "{name} ಜೊತೆ ಅಪರಾಧ ಮಾಡಿದ",
  "the subject": "ವಿಷಯ",
  "this investigation": "ಈ ತನಿಖೆ",
  "{headline} · {hops} steps away": "{headline} · {hops} ಹೆಜ್ಜೆ ದೂರ",
  "{headline} — reached through shared cases": "{headline} — ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳ ಮೂಲಕ ತಲುಪಲಾಗಿದೆ",
  "Named in the records": "ದಾಖಲೆಗಳಲ್ಲಿ ಹೆಸರಿಸಲಾಗಿದೆ",
  "Direct co-offenders": "ನೇರ ಸಹ-ಅಪರಾಧಿಗಳು",
  "Strongest wider connections": "ಪ್ರಬಲ ವಿಶಾಲ ಸಂಪರ್ಕಗಳು",
  "Named in the case records": "ಪ್ರಕರಣ ದಾಖಲೆಗಳಲ್ಲಿ ಹೆಸರಿಸಲಾಗಿದೆ",
  "Stated in the case records": "ಪ್ರಕರಣ ದಾಖಲೆಗಳಲ್ಲಿ ಹೇಳಲಾಗಿದೆ",
  "Inferred by Veritas from cases these people share": "ಈ ಜನರು ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳಿಂದ Veritas ಊಹಿಸಿದೆ",
  "Inferred by Veritas from shared cases": "ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳಿಂದ Veritas ಊಹಿಸಿದೆ",

  // ---- WhyChain -----------------------------------------------------------------
  "Rests on": "ಆಧಾರಿತ",
  "How it was arrived at": "ಇದನ್ನು ಹೇಗೆ ತಲುಪಲಾಯಿತು",
  "Why it qualifies": "ಇದು ಏಕೆ ಅರ್ಹತೆ ಪಡೆಯುತ್ತದೆ",
  "What it does not mean": "ಇದರ ಅರ್ಥವೇನಲ್ಲ",
  "Some of this chain could not be reconstructed. What is shown is what the records themselves support — nothing has been filled in.":
    "ಈ ಸರಪಳಿಯ ಕೆಲವು ಭಾಗವನ್ನು ಪುನರ್ನಿರ್ಮಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ತೋರಿಸಿರುವುದು ದಾಖಲೆಗಳೇ ಬೆಂಬಲಿಸುವುದು — ಏನನ್ನೂ ತುಂಬಿಲ್ಲ.",
  "Ask next": "ಮುಂದೆ ಕೇಳಿ",
  "Tracing where this came from…": "ಇದು ಎಲ್ಲಿಂದ ಬಂತು ಎಂದು ಪತ್ತೆಹಚ್ಚಲಾಗುತ್ತಿದೆ…",
  "Could not load this": "ಇದನ್ನು ಲೋಡ್ ಮಾಡಲಾಗಲಿಲ್ಲ",
  "Prediction": "ಮುನ್ಸೂಚನೆ",

  // ---- Progress / ReasoningTrace --------------------------------------------
  "Investigating": "ತನಿಖೆ ನಡೆಯುತ್ತಿದೆ",
  "Understanding the request": "ವಿನಂತಿಯನ್ನು ಅರ್ಥಮಾಡಿಕೊಳ್ಳಲಾಗುತ್ತಿದೆ",
  "Retrieving records": "ದಾಖಲೆಗಳನ್ನು ಪಡೆಯಲಾಗುತ್ತಿದೆ",
  "Verifying evidence": "ಸಾಕ್ಷ್ಯವನ್ನು ಪರಿಶೀಲಿಸಲಾಗುತ್ತಿದೆ",
  "Preparing the result": "ಫಲಿತಾಂಶವನ್ನು ಸಿದ್ಧಪಡಿಸಲಾಗುತ್ತಿದೆ",
  "Reading the question and the case in play": "ಪ್ರಶ್ನೆ ಮತ್ತು ಪ್ರಸ್ತುತ ಪ್ರಕರಣವನ್ನು ಓದಲಾಗುತ್ತಿದೆ",
  "Searching the records you are cleared to see": "ನೀವು ನೋಡಲು ಅನುಮತಿಸಿದ ದಾಖಲೆಗಳಲ್ಲಿ ಹುಡುಕಲಾಗುತ್ತಿದೆ",
  "Checking what the records actually support": "ದಾಖಲೆಗಳು ನಿಜವಾಗಿ ಏನನ್ನು ಬೆಂಬಲಿಸುತ್ತವೆ ಎಂದು ಪರಿಶೀಲಿಸಲಾಗುತ್ತಿದೆ",
  "Writing the finding and its citations": "ಶೋಧನೆ ಮತ್ತು ಅದರ ಉಲ್ಲೇಖಗಳನ್ನು ಬರೆಯಲಾಗುತ್ತಿದೆ",
  "How this was answered": "ಇದನ್ನು ಹೇಗೆ ಉತ್ತರಿಸಲಾಯಿತು",
  "steps": "ಹಂತಗಳು",

  // ---- AlertBell --------------------------------------------------------------
  "District anomaly alerts": "ಜಿಲ್ಲಾ ಅಸಂಗತ ಎಚ್ಚರಿಕೆಗಳು",
  "Alerts": "ಎಚ್ಚರಿಕೆಗಳು",
  "District anomalies": "ಜಿಲ್ಲಾ ಅಸಂಗತಗಳು",
  "No anomalies since you signed in. This feed reports districts whose case volume departs from their own recent baseline.":
    "ನೀವು ಸೈನ್ ಇನ್ ಆದಾಗಿನಿಂದ ಯಾವುದೇ ಅಸಂಗತತೆಗಳಿಲ್ಲ. ಈ ಫೀಡ್ ತಮ್ಮದೇ ಇತ್ತೀಚಿನ ಮಾನದಂಡದಿಂದ ಪ್ರಕರಣ ಪ್ರಮಾಣ ವ್ಯತ್ಯಾಸಗೊಳ್ಳುವ ಜಿಲ್ಲೆಗಳನ್ನು ವರದಿ ಮಾಡುತ್ತದೆ.",
  "Decision support. Nothing here triggers an action on its own.":
    "ನಿರ್ಧಾರ ಬೆಂಬಲ. ಇಲ್ಲಿ ಯಾವುದೂ ಸ್ವತಃ ಕ್ರಿಯೆಯನ್ನು ಪ್ರಚೋದಿಸುವುದಿಲ್ಲ.",
  "Far more FIRs than usual": "ಎಂದಿಗಿಂತ ಹೆಚ್ಚು FIR ಗಳು",
  "Well above the usual count": "ಸಾಮಾನ್ಯ ಸಂಖ್ಯೆಗಿಂತ ಗಣನೀಯವಾಗಿ ಹೆಚ್ಚು",
  "Above the usual count": "ಸಾಮಾನ್ಯ ಸಂಖ್ಯೆಗಿಂತ ಹೆಚ್ಚು",
  "Far fewer FIRs than usual": "ಎಂದಿಗಿಂತ ಬಹಳ ಕಡಿಮೆ FIR ಗಳು",
  "Well below the usual count": "ಸಾಮಾನ್ಯ ಸಂಖ್ಯೆಗಿಂತ ಗಣನೀಯವಾಗಿ ಕಡಿಮೆ",
  "Below the usual count": "ಸಾಮಾನ್ಯ ಸಂಖ್ಯೆಗಿಂತ ಕಡಿಮೆ",
  "Close to the usual count": "ಸಾಮಾನ್ಯ ಸಂಖ್ಯೆಗೆ ಹತ್ತಿರ",

  // ---- VoiceRecorder ------------------------------------------------------------
  "Recording a question": "ಪ್ರಶ್ನೆಯನ್ನು ರೆಕಾರ್ಡ್ ಮಾಡಲಾಗುತ್ತಿದೆ",
  "Waiting for microphone permission": "ಮೈಕ್ರೋಫೋನ್ ಅನುಮತಿಗಾಗಿ ಕಾಯಲಾಗುತ್ತಿದೆ",
  "Recording. Choose send or discard.": "ರೆಕಾರ್ಡ್ ಆಗುತ್ತಿದೆ. ಕಳುಹಿಸಿ ಅಥವಾ ತಿರಸ್ಕರಿಸಿ ಆಯ್ಕೆಮಾಡಿ.",
  "Discard this recording": "ಈ ರೆಕಾರ್ಡಿಂಗ್ ಅನ್ನು ತಿರಸ್ಕರಿಸಿ",
  "Discard": "ತಿರಸ್ಕರಿಸಿ",
  "Stop recording and ask": "ರೆಕಾರ್ಡಿಂಗ್ ನಿಲ್ಲಿಸಿ ಮತ್ತು ಕೇಳಿ",
  "Send": "ಕಳುಹಿಸಿ",
  "Microphone blocked. Allow it in your browser's site settings, then try again.":
    "ಮೈಕ್ರೋಫೋನ್ ನಿರ್ಬಂಧಿಸಲಾಗಿದೆ. ನಿಮ್ಮ ಬ್ರೌಸರ್‌ನ ಸೈಟ್ ಸೆಟ್ಟಿಂಗ್‌ಗಳಲ್ಲಿ ಅನುಮತಿಸಿ, ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
  "This browser cannot record audio. Type the question instead.":
    "ಈ ಬ್ರೌಸರ್ ಆಡಿಯೋ ರೆಕಾರ್ಡ್ ಮಾಡಲಾಗುವುದಿಲ್ಲ. ಬದಲಿಗೆ ಪ್ರಶ್ನೆಯನ್ನು ಟೈಪ್ ಮಾಡಿ.",
  "Ask by voice, in English or Kannada": "ಇಂಗ್ಲಿಷ್ ಅಥವಾ ಕನ್ನಡದಲ್ಲಿ ಧ್ವನಿಯ ಮೂಲಕ ಕೇಳಿ",
  "Ask by voice": "ಧ್ವನಿಯ ಮೂಲಕ ಕೇಳಿ",
  "Speak": "ಮಾತನಾಡಿ",

  // ---- viz: TrendView / SankeyView / TimelineView / NetworkView / MapView -------
  "cases / day": "ಪ್ರಕರಣಗಳು / ದಿನ",
  "projected daily volume": "ಯೋಜಿತ ದೈನಂದಿನ ಪ್ರಮಾಣ",
  "likely range": "ಸಂಭಾವ್ಯ ವ್ಯಾಪ್ತಿ",
  "Transfer size": "ವರ್ಗಾವಣೆ ಗಾತ್ರ",
  "smaller → larger": "ಚಿಕ್ಕದು → ದೊಡ್ಡದು",
  "Left to right is the direction of payment.": "ಎಡದಿಂದ ಬಲಕ್ಕೆ ಪಾವತಿಯ ದಿಕ್ಕು.",
  "No dated events": "ಯಾವುದೇ ದಿನಾಂಕದ ಘಟನೆಗಳಿಲ್ಲ",
  "Nothing in these records carries a date that could be placed on a chronology.":
    "ಈ ದಾಖಲೆಗಳಲ್ಲಿ ಕಾಲಾನುಕ್ರಮದಲ್ಲಿ ಇರಿಸಬಹುದಾದ ಯಾವುದೇ ದಿನಾಂಕ ಇಲ್ಲ.",
  "Save this event to the case's investigation board": "ಈ ಘಟನೆಯನ್ನು ಪ್ರಕರಣದ ತನಿಖಾ ಬೋರ್ಡ್‌ಗೆ ಉಳಿಸಿ",
  "Pin": "ಪಿನ್",
  "Events close together in time are not, on that basis alone, reported as connected.":
    "ಸಮಯದಲ್ಲಿ ಹತ್ತಿರವಿರುವ ಘಟನೆಗಳನ್ನು, ಆ ಆಧಾರದ ಮೇಲೆ ಮಾತ್ರ, ಸಂಪರ್ಕಿತವೆಂದು ವರದಿ ಮಾಡಲಾಗುವುದಿಲ್ಲ.",
  "No recorded connection between": "ನಡುವೆ ಯಾವುದೇ ದಾಖಲಿತ ಸಂಪರ್ಕವಿಲ್ಲ",
  "and": "ಮತ್ತು",
  "Peripheral": "ಪರಿಧೀಯ",
  "Connected": "ಸಂಪರ್ಕಿತ",
  "Well connected": "ಚೆನ್ನಾಗಿ ಸಂಪರ್ಕಿತ",
  "Central to this network": "ಈ ಜಾಲದ ಕೇಂದ್ರ",
  "subject of this search": "ಈ ಹುಡುಕಾಟದ ವಿಷಯ",
  "named in the case records": "ಪ್ರಕರಣ ದಾಖಲೆಗಳಲ್ಲಿ ಹೆಸರಿಸಲಾಗಿದೆ",
  "offended alongside the subject": "ವಿಷಯದ ಜೊತೆ ಅಪರಾಧ ಮಾಡಿದ",
  "reached through shared cases": "ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳ ಮೂಲಕ ತಲುಪಲಾಗಿದೆ",
  "Subject of this search": "ಈ ಹುಡುಕಾಟದ ವಿಷಯ",
  "Offended alongside the subject on a shared case": "ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣದಲ್ಲಿ ವಿಷಯದ ಜೊತೆ ಅಪರಾಧ ಮಾಡಿದ",
  "Reached through a chain of shared cases — not accused in this case":
    "ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳ ಸರಪಳಿಯ ಮೂಲಕ ತಲುಪಲಾಗಿದೆ — ಈ ಪ್ರಕರಣದಲ್ಲಿ ಆರೋಪಿಯಲ್ಲ",
  "Connections in view": "ವೀಕ್ಷಣೆಯಲ್ಲಿನ ಸಂಪರ್ಕಗಳು",
  "Distance": "ದೂರ",
  "{n} step(s)": "{n} ಹೆಜ್ಜೆ(ಗಳು)",
  "Hide chain": "ಸರಪಳಿಯನ್ನು ಮರೆಮಾಡಿ",
  "Why connected?": "ಏಕೆ ಸಂಪರ್ಕಿತ?",
  "Show me the timeline for {name}.": "{name} ಅವರ ಕಾಲಾನುಕ್ರಮವನ್ನು ತೋರಿಸಿ.",
  "Trace money": "ಹಣ ಪತ್ತೆಹಚ್ಚಿ",
  "Clear": "ತೆರವುಗೊಳಿಸಿ",
  "Reached through shared cases": "ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳ ಮೂಲಕ ತಲುಪಲಾಗಿದೆ",
  "Connected through shared cases": "ಹಂಚಿಕೊಂಡ ಪ್ರಕರಣಗಳ ಮೂಲಕ ಸಂಪರ್ಕಿತ",
  "peripheral → central": "ಪರಿಧೀಯ → ಕೇಂದ್ರ",
  "Connectedness within this graph — not a risk score, and not an accusation.":
    "ಈ ಗ್ರಾಫ್‌ನೊಳಗಿನ ಸಂಪರ್ಕತೆ — ಅಪಾಯದ ಅಂಕವಲ್ಲ, ಆರೋಪವೂ ಅಲ್ಲ.",
  "Click to select": "ಆಯ್ಕೆ ಮಾಡಲು ಕ್ಲಿಕ್ ಮಾಡಿ",
  "Filed {date}": "{date} ರಂದು ದಾಖಲಿಸಲಾಗಿದೆ",
  "filed {date}": "{date} ರಂದು ದಾಖಲಿಸಲಾಗಿದೆ",
  "{n} case(s) here": "ಇಲ್ಲಿ {n} ಪ್ರಕರಣ(ಗಳು)",
  "Click to zoom in": "ಝೂಮ್ ಮಾಡಲು ಕ್ಲಿಕ್ ಮಾಡಿ",
  "Plotted here because the case file records these coordinates.":
    "ಪ್ರಕರಣ ಫೈಲ್ ಈ ನಿರ್ದೇಶಾಂಕಗಳನ್ನು ದಾಖಲಿಸುವುದರಿಂದ ಇಲ್ಲಿ ಗುರುತಿಸಲಾಗಿದೆ.",
  "Why is this here?": "ಇದು ಏಕೆ ಇಲ್ಲಿದೆ?",
  "What happened here?": "ಇಲ್ಲಿ ಏನಾಯಿತು?",
  "Who was involved?": "ಯಾರು ಭಾಗಿಯಾಗಿದ್ದರು?",
  "Who are all involved?": "ಎಲ್ಲರೂ ಯಾರು ಭಾಗಿಯಾಗಿದ್ದಾರೆ?",
  "Show me the timeline.": "ಕಾಲಾನುಕ್ರಮವನ್ನು ತೋರಿಸಿ.",
  "Related cases": "ಸಂಬಂಧಿತ ಪ್ರಕರಣಗಳು",
  "Find similar cases.": "ಇದೇ ರೀತಿಯ ಪ್ರಕರಣಗಳನ್ನು ಹುಡುಕಿ.",
  "Add to board": "ಬೋರ್ಡ್‌ಗೆ ಸೇರಿಸಿ",
  "Hide density": "ಸಾಂದ್ರತೆಯನ್ನು ಮರೆಮಾಡಿ",
  "Show density": "ಸಾಂದ್ರತೆಯನ್ನು ತೋರಿಸಿ",
  "Cases here — click to expand": "ಇಲ್ಲಿ ಪ್ರಕರಣಗಳು — ವಿಸ್ತರಿಸಲು ಕ್ಲಿಕ್ ಮಾಡಿ",
  "Selected": "ಆಯ್ಕೆಮಾಡಲಾಗಿದೆ",
  "Hotspot density": "ಹಾಟ್‌ಸ್ಪಾಟ್ ಸಾಂದ್ರತೆ",

  // ---- page.tsx / SCOPE ---------------------------------------------------------
  "Station scope": "ಠಾಣಾ ವ್ಯಾಪ್ತಿ",
  "District scope": "ಜಿಲ್ಲಾ ವ್ಯಾಪ್ತಿ",
  "State scope": "ರಾಜ್ಯ ವ್ಯಾಪ್ತಿ",
  "Scoped access": "ವ್ಯಾಪ್ತಿ ಪ್ರವೇಶ",
  "This rank was entered without a verified badge, so no record-scoped question can be answered. Switch and sign in with a real badge to continue.":
    "ಈ ಶ್ರೇಣಿಯನ್ನು ಪರಿಶೀಲಿತ ಬ್ಯಾಡ್ಜ್ ಇಲ್ಲದೆ ಪ್ರವೇಶಿಸಲಾಗಿದೆ, ಆದ್ದರಿಂದ ಯಾವುದೇ ದಾಖಲೆ-ವ್ಯಾಪ್ತಿಯ ಪ್ರಶ್ನೆಗೆ ಉತ್ತರಿಸಲಾಗುವುದಿಲ್ಲ. ಮುಂದುವರಿಯಲು ಬದಲಿಸಿ ಮತ್ತು ನಿಜವಾದ ಬ್ಯಾಡ್ಜ್‌ನೊಂದಿಗೆ ಸೈನ್ ಇನ್ ಮಾಡಿ.",
  "The connection to the investigation engine was lost.": "ತನಿಖಾ ಇಂಜಿನ್‌ಗೆ ಸಂಪರ್ಕ ಕಡಿದುಹೋಗಿದೆ.",
  "Exporting…": "ರಫ್ತು ಮಾಡಲಾಗುತ್ತಿದೆ…",
  "PDF downloaded.": "PDF ಡೌನ್‌ಲೋಡ್ ಆಗಿದೆ.",
  "No PDF renderer on this deployment — a printable HTML copy was downloaded.":
    "ಈ ನಿಯೋಜನೆಯಲ್ಲಿ PDF ರೆಂಡರರ್ ಇಲ್ಲ — ಮುದ್ರಿಸಬಹುದಾದ HTML ಪ್ರತಿಯನ್ನು ಡೌನ್‌ಲೋಡ್ ಮಾಡಲಾಗಿದೆ.",
  "Export failed.": "ರಫ್ತು ವಿಫಲವಾಗಿದೆ.",
};

/** Patterns for strings a component composes at render time — a fixed label
 *  glued to a number that a plain dictionary lookup can never match exactly
 *  (`"Network influence · 0.010"`, `"73 cases"`, …). Each entry only ever
 *  replaces the fixed, translatable part and leaves the number untouched. */
const PATTERNS: [RegExp, (m: RegExpMatchArray) => string][] = [
  // "Network influence · 0.010" / "Relative density · 1.00" / "Text match · 66%"
  [/^(Network influence|Relative density|Text match|Expected daily range) · (.+)$/,
    (m) => `${{ "Network influence": "ಜಾಲ ಪ್ರಭಾವ", "Relative density": "ಸಾಪೇಕ್ಷ ಸಾಂದ್ರತೆ",
      "Text match": "ಪಠ್ಯ ಹೊಂದಾಣಿಕೆ", "Expected daily range": "ನಿರೀಕ್ಷಿತ ದೈನಂದಿನ ವ್ಯಾಪ್ತಿ" }[m[1]]} · ${m[2]}`],
  // "≈74 cases projected"
  [/^≈([\d,]+) cases projected$/, (m) => `≈${m[1]} ಪ್ರಕರಣಗಳು ಯೋಜಿಸಲಾಗಿದೆ`],
  // "Low/Moderate/Elevated/Severe concentration"
  [/^(Low|Moderate|Elevated|Severe) concentration$/,
    (m) => `${{ Low: "ಕಡಿಮೆ", Moderate: "ಮಧ್ಯಮ", Elevated: "ಏರಿದ", Severe: "ತೀವ್ರ" }[m[1]]} ಕೇಂದ್ರೀಕರಣ`],
  // "Closely related record" / "Related record" / "Loosely related record"
  [/^(Closely related|Related|Loosely related) record$/,
    (m) => `${{ "Closely related": "ನಿಕಟ ಸಂಬಂಧಿತ", "Related": "ಸಂಬಂಧಿತ", "Loosely related": "ಸಡಿಲ ಸಂಬಂಧಿತ" }[m[1]]} ದಾಖಲೆ`],
  // "{n}-day outlook"
  [/^(\d+)-day outlook$/, (m) => `${m[1]}-ದಿನಗಳ ಮುನ್ಸೂಚನೆ`],
  // "and {n} more — the Network view has all of them." / "and {n} more in the Network view."
  [/^and (\d[\d,]*) more — the Network view has all of them\.$/,
    (m) => `ಮತ್ತು ${m[1]} ಹೆಚ್ಚು — ನೆಟ್‌ವರ್ಕ್ ವೀಕ್ಷಣೆಯಲ್ಲಿ ಎಲ್ಲವೂ ಇವೆ.`],
  [/^and (\d[\d,]*) more in the Network view\.$/,
    (m) => `ಮತ್ತು ${m[1]} ಹೆಚ್ಚು ನೆಟ್‌ವರ್ಕ್ ವೀಕ್ಷಣೆಯಲ್ಲಿ.`],
  // Per-entity questions built with the name already interpolated in — these
  // recur across ChatPane's follow-ups, CommandPalette, CaseOverview and the
  // graph/map probe cards, always as one of these exact shapes.
  [/^Does (.+) have priors\?$/, (m) => `${m[1]} ಅವರಿಗೆ ಪೂರ್ವ ದಾಖಲೆ ಇದೆಯೇ?`],
  [/^What should I ask (.+)\?$/, (m) => `${m[1]} ಅವರನ್ನು ನಾನು ಏನು ಕೇಳಬೇಕು?`],
  [/^Who are the associates of (.+)\?$/, (m) => `${m[1]} ಅವರ ಸಹಚರರು ಯಾರು?`],
  [/^Show me the timeline for (.+?)\.?$/, (m) => `${m[1]} ಅವರ ಕಾಲಾನುಕ್ರಮವನ್ನು ತೋರಿಸಿ`],
  [/^Where did (.+)'s money go\?$/, (m) => `${m[1]} ಅವರ ಹಣ ಎಲ್ಲಿ ಹೋಯಿತು?`],
  [/^Examine (.+)$/, (m) => `${m[1]} ಅನ್ನು ಪರಿಶೀಲಿಸಿ`],
  [/^Check whether (.+) has priors$/, (m) => `${m[1]} ಅವರಿಗೆ ಪೂರ್ವ ದಾಖಲೆ ಇದೆಯೇ ಎಂದು ಪರಿಶೀಲಿಸಿ`],
  [/^Show the network around (.+)$/, (m) => `${m[1]} ಸುತ್ತಲಿನ ಜಾಲವನ್ನು ತೋರಿಸಿ`],
  [/^Cases in (.+)$/, (m) => `${m[1]} ನಲ್ಲಿ ಪ್ರಕರಣಗಳು`],
  // `lib/metrics.ts`'s `plural(n, one, many)` — "12 known associates", "3 stalled
  // cases" — built at render time from a count and one of a fixed set of nouns.
  // Unrecognised nouns fall through untranslated (m[0]) rather than breaking.
  [/^([\d,]+) (.+)$/, (m) => COUNT_NOUNS[m[2]] ? `${m[1]} ${COUNT_NOUNS[m[2]]}` : m[0]],
];

const COUNT_NOUNS: Record<string, string> = {
  "person": "ವ್ಯಕ್ತಿ", "people": "ಜನರು",
  "known associate": "ಪರಿಚಿತ ಸಹಚರ", "known associates": "ಪರಿಚಿತ ಸಹಚರರು",
  "flagged transaction": "ಗುರುತಿಸಲಾದ ವಹಿವಾಟು", "flagged transactions": "ಗುರುತಿಸಲಾದ ವಹಿವಾಟುಗಳು",
  "stalled case": "ಸ್ಥಗಿತಗೊಂಡ ಪ್ರಕರಣ", "stalled cases": "ಸ್ಥಗಿತಗೊಂಡ ಪ್ರಕರಣಗಳು",
  "connection": "ಸಂಪರ್ಕ", "connections": "ಸಂಪರ್ಕಗಳು",
  "source account": "ಮೂಲ ಖಾತೆ", "source accounts": "ಮೂಲ ಖಾತೆಗಳು",
  "destination account": "ಗಮ್ಯ ಖಾತೆ", "destination accounts": "ಗಮ್ಯ ಖಾತೆಗಳು",
  "dated event": "ದಿನಾಂಕದ ಘಟನೆ", "dated events": "ದಿನಾಂಕದ ಘಟನೆಗಳು",
  "distinct case": "ವಿಭಿನ್ನ ಪ್ರಕರಣ", "distinct cases": "ವಿಭಿನ್ನ ಪ್ರಕರಣಗಳು",
  "police station": "ಪೊಲೀಸ್ ಠಾಣೆ", "police stations": "ಪೊಲೀಸ್ ಠಾಣೆಗಳು",
  "station": "ಠಾಣೆ", "stations": "ಠಾಣೆಗಳು",
  "FIR": "FIR", "FIRs": "FIRs",
};

/** Fills `{token}` placeholders in a (possibly already-translated) template. */
function fill(s: string, vars?: Record<string, string | number>): string {
  if (!vars) return s;
  let out = s;
  for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
  return out;
}

/** `translate(english, lang, vars?)` — looks up `english` (after filling any
 *  `{token}`s) in the Kannada dictionary when `lang` is "kn", otherwise
 *  returns the filled English string unchanged. A miss just renders in
 *  English rather than breaking, so coverage can grow incrementally.
 *
 *  Takes `lang` as a plain argument (not just via the hook below) so a
 *  component holding the `language` state itself — page.tsx, before its
 *  own `<LangProvider>` wraps anything — can translate without depending on
 *  context timing. */
export function translate(s: string, lang: Lang, vars?: Record<string, string | number>): string {
  const filled = fill(s, vars);
  if (lang === "en") return filled;
  if (filled in KN) return KN[filled];
  if (s in KN) return fill(KN[s], vars);
  for (const [re, make] of PATTERNS) {
    const m = filled.match(re);
    if (m) return make(m);
  }
  return filled;
}

/** `t(english, vars?)` — the same lookup, reading the current language from
 *  context. Use inside any component rendered under `<LangProvider>`. */
export function useT() {
  const lang = useLang();
  return (s: string, vars?: Record<string, string | number>) => translate(s, lang, vars);
}
