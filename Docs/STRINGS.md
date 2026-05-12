# String table (STBL) entries — Layer A

Add these in Sims 4 Studio under **Add → String Table** (locale `ENG_US` to start).
Each `0xTBD_STBL_KEY_*` in the XML files must be replaced with the hex hash S4S generates
for the matching key here.

## Pie menu
| Key | English | German (DEU) |
|---|---|---|
| `HC_PIE_CATEGORY_HISTORIAN` | Historian | Historiker:in |

## Interactions
| Key | English | German (DEU) |
|---|---|---|
| `HC_INTERACTION_TRANSCRIBE_MANUSCRIPT` | Transcribe Manuscript | Handschrift abschreiben |
| `HC_INTERACTION_ANALYZE_PRIMARY_SOURCE` | Analyze Primary Source | Primärquelle analysieren |
| `HC_INTERACTION_PRESENT_AT_SYMPOSIUM` | Present at Symposium | Tagungsvortrag halten |
| `HC_INTERACTION_HABILITATION_LECTURE` | Habilitation Lecture | Habilitationsvortrag halten |
| `HC_INTERACTION_SUPERVISE_DISSERTATION` | Supervise Dissertation | Doktorand:in betreuen |

## Promotion notification titles (used by `historian_career.py`)
The script currently builds the notification text in code (bilingual single popup). If we
later want them localized through STBL, add these keys and switch the script to
`LocalizationHelperTuning.get_localized_string`:

| Key | English | German (DEU) |
|---|---|---|
| `HC_PROMO_TITLE` | Promotion! | Beförderung! |
| `HC_PROMO_TIER_1` | You are now a Research Assistant. | Sie sind jetzt Wissenschaftliche Hilfskraft. |
| `HC_PROMO_TIER_2` | You are now a PhD Candidate. | Sie sind jetzt Doktorand:in. |
| `HC_PROMO_TIER_3` | You are now a Postdoctoral Researcher. | Sie sind jetzt Postdoktorand:in. |
| `HC_PROMO_TIER_4` | You are now a Junior Professor. | Sie sind jetzt Juniorprofessor:in. |
| `HC_PROMO_TIER_5` | You are now a Full Professor (W3). | Sie sind jetzt Professor:in (W3). |

---

# Layer B additions

## Career meta
| Key | English | German |
|---|---|---|
| `HC_CAREER_NAME` | Historian | Historiker:in |
| `HC_CAREER_DESCRIPTION` | Research the past, write the future. Requires a History degree (Discover University). | Erforsche die Vergangenheit, schreibe die Zukunft. Voraussetzung: Geschichtsstudium (Discover University). |

## Career level titles & descriptions
| Key | English | German |
|---|---|---|
| `HC_LEVEL_1_TITLE` | Research Assistant | Wissenschaftliche Hilfskraft |
| `HC_LEVEL_1_DESC` | Part-time archival work for a faculty member. §40/h, 09:00–13:00. | Teilzeit-Archivarbeit für eine:n Hochschullehrende:n. §40/h, 09:00–13:00. |
| `HC_LEVEL_1_DAILY` | Read non-fiction and transcribe sources. | Sachbücher lesen und Quellen abschreiben. |
| `HC_LEVEL_2_TITLE` | PhD Candidate | Doktorand:in |
| `HC_LEVEL_2_DESC` | Work on your dissertation. §70/h, 09:00–17:00. | Promotion vorbereiten. §70/h, 09:00–17:00. |
| `HC_LEVEL_2_DAILY` | Analyze sources and keep transcribing. | Quellen analysieren und weiter abschreiben. |
| `HC_LEVEL_3_TITLE` | Postdoctoral Researcher | Postdoktorand:in |
| `HC_LEVEL_3_DESC` | Independent research and conference circuit. §120/h. Requires Research & Debate 7. | Eigenständige Forschung und Konferenzauftritte. §120/h. Voraussetzung: Forschung & Debatte 7. |
| `HC_LEVEL_3_DAILY` | Present at a symposium; analyze sources. | Vortrag auf einer Tagung halten; Quellen analysieren. |
| `HC_LEVEL_4_TITLE` | Junior Professor | Juniorprofessor:in |
| `HC_LEVEL_4_DESC` | Lead teaching and prep your Habilitation. §200/h, 10:00–18:00. Requires Writing 7. | Lehre verantworten und Habilitation vorbereiten. §200/h, 10:00–18:00. Voraussetzung: Schreiben 7. |
| `HC_LEVEL_4_DAILY` | Deliver a Habilitation lecture; speak at symposia. | Habilitationsvortrag halten; Tagungsvorträge halten. |
| `HC_LEVEL_5_TITLE` | Full Professor (W3) | Professor:in (W3) |
| `HC_LEVEL_5_DESC` | A Lehrstuhl is yours. §340/h. Requires Research & Debate 10 + Writing 10. | Sie haben einen Lehrstuhl inne. §340/h. Voraussetzung: Forschung & Debatte 10 + Schreiben 10. |
| `HC_LEVEL_5_DAILY` | Supervise dissertations and keep publishing. | Doktorand:innen betreuen und weiter publizieren. |

## Objective texts
| Key | English | German |
|---|---|---|
| `HC_OBJ_TRANSCRIBE_X2` | Transcribe a manuscript (2). | Eine Handschrift abschreiben (2). |
| `HC_OBJ_ANALYZE` | Analyze a primary source. | Eine Primärquelle analysieren. |
| `HC_OBJ_SYMPOSIUM` | Present at a symposium. | Vortrag auf einer Tagung halten. |
| `HC_OBJ_HABILITATION` | Deliver a Habilitation lecture. | Habilitationsvortrag halten. |
| `HC_OBJ_SUPERVISE` | Supervise a dissertation. | Doktorand:in betreuen. |
| `HC_OBJ_READ_BOOK` | Read a non-fiction book. | Ein Sachbuch lesen. |

## Long aspiration "Historian's Calling"
| Key | English | German |
|---|---|---|
| `HC_ASPTRACK_NAME` | Historian's Calling | Berufung Historiker:in |
| `HC_ASPTRACK_DESC` | Climb the German academic Karriereleiter from HiWi to Lehrstuhl. | Aufstieg auf der Karriereleiter von HiWi bis Lehrstuhl. |
| `HC_ASP_T1_NAME` | Begin Your Career | Karriere beginnen |
| `HC_ASP_T1_DESC` | Work two manuscript-transcription shifts. | Zwei Schichten Quellenabschrift. |
| `HC_ASP_T2_NAME` | Defend Your Dissertation | Dissertation verteidigen |
| `HC_ASP_T2_DESC` | Analyze sources and speak at a symposium. | Quellen analysieren und Tagungsvortrag halten. |
| `HC_ASP_T3_NAME` | Habilitate | Habilitieren |
| `HC_ASP_T3_DESC` | Deliver a successful Habilitation lecture. | Erfolgreichen Habilitationsvortrag halten. |
| `HC_ASP_T4_NAME` | Hold a Lehrstuhl | Lehrstuhl innehaben |
| `HC_ASP_T4_DESC` | Supervise a dissertation as a full professor. | Als ordentliche:r Professor:in eine Dissertation betreuen. |

## Reward trait
| Key | English | German |
|---|---|---|
| `HC_TRAIT_RENOWN_NAME` | Habilitation Renown | Habilitationsruhm |
| `HC_TRAIT_RENOWN_DESC` | Years in the archive have left their mark. Slight focus boost in libraries; small writing-speed bonus. | Jahre im Archiv haben Spuren hinterlassen. Leichter Fokus-Boost in Bibliotheken; kleiner Schreib-Bonus. |

## Chance card — Plagiarism
| Key | English | German |
|---|---|---|
| `HC_CARD_PLAGIARISM_TITLE` | A Plagiarism Accusation | Plagiatsvorwurf |
| `HC_CARD_PLAGIARISM_BODY` | A colleague claims a paragraph of your dissertation was copied from their unpublished draft. The story is making the rounds in your department. How do you respond? | Ein:e Kollege:in behauptet, ein Absatz Ihrer Dissertation stamme aus ihrem unveröffentlichten Entwurf. Im Fachbereich macht die Sache die Runde. Wie reagieren Sie? |
| `HC_CARD_PLAGIARISM_OPT_A` | Disclose and apologize. | Offenlegen und sich entschuldigen. |
| `HC_CARD_PLAGIARISM_OPT_B` | Stonewall the accusation. | Den Vorwurf aussitzen. |
